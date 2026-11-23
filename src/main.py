"""SoccerSim 策略入口 —— 比赛策略主逻辑都在这里,改打法就改这个文件。

结构(由浅入深):
- main.py(本文件):比赛策略。play() 按 Phase 状态机分派到 _act_*;各 _act_* 选出
  attacker(离球最近)并直接调 player 动作。
- player.py:Player 控制 handle + 高层动作(attack / take_kickoff /
  move_to_position / walk_to);想加拐棍/技术动作直接改它。
- utils/:走位/几何/避障工具(opponent_goal / dist / angle_to ...)。
- framework/:平台管线,用户不改。

改打法主要改本文件:Phase 状态机、各 _act_* 行为、站位公式。
"""

from __future__ import annotations

import logging
import math
from enum import Enum

from booster_agent_framework import AgentBase

from .framework.agent import SoccerAgentMixin
from .framework.types import KICKING_TEAM_NONE, Context, GameState, SetPlay
from .param import *
from .player import Player
from .utils import (
    angle_to,
    clamp,
    dist,
    normalize_angle,
    opponent_goal,
    own_goal,
)


_log = logging.getLogger(__name__)


# ======================================================================
# Phase 状态机 —— 比赛阶段分类
# ======================================================================


class Phase(Enum):
    """比赛阶段。顶层状态机,决定当前是正常拼抢/开球/定位球/准备/停止。"""
    NORMAL = "normal"              # PLAYING 正常拼抢
    OUR_KICKOFF = "our_kickoff"    # 我方开球(SET+PLAYING 初期,take_kickoff)
    OPP_KICKOFF = "opp_kickoff"    # 对方开球(避让)
    OUR_SET_PLAY = "our_set_play"  # 我方定位球(任意球/角球/球门球)
    OPP_SET_PLAY = "opp_set_play"  # 对方定位球(避让)
    READY = "ready"                # READY 走位
    STOPPED = "stopped"            # SET(非开球重开) / INITIAL / FINISHED / stopped


def get_phase(context: Context) -> Phase:
    """根据裁判机状态判断当前比赛阶段。"""
    g = context.game
    if g is None:
        return Phase.STOPPED

    state = g.state

    # READY:走 ready 位
    if state == GameState.READY:
        return Phase.READY

    # PLAYING:正常拼抢 or 开球/定位球执行中
    if state == GameState.PLAYING and not g.stopped:
        # 定位球:set_play != NONE,kicking_team 指示哪方
        if g.set_play != SetPlay.NONE and g.kicking_team != KICKING_TEAM_NONE:
            our_team = context.team_id
            if g.kicking_team == our_team:
                return Phase.OUR_SET_PLAY
            else:
                return Phase.OPP_SET_PLAY

        # 开球:secondary_time > 0(倒计时窗口),kicking_team 指示哪方
        if g.secondary_time > 0 and g.kicking_team != KICKING_TEAM_NONE:
            our_team = context.team_id
            if g.kicking_team == our_team:
                return Phase.OUR_KICKOFF
            else:
                return Phase.OPP_KICKOFF

        # 正常拼抢
        return Phase.NORMAL

    # SET / INITIAL / FINISHED / stopped:站定
    return Phase.STOPPED

def get_set_play_type(context: Context) -> SetPlay:
    """当前生效的定位球类型;无定位球(或无裁判机数据)时返回 ``SetPlay.NONE``。

    直接读裁判机的 ``set_play`` 字段,不区分是哪方主罚 —— 哪方由 :func:`get_phase`
    (OUR_SET_PLAY / OPP_SET_PLAY)判定。这里只回答"是什么类型的定位球"。

    共 7 种可能返回值(见 framework.types.SetPlay):
    - ``NONE``:无定位球(正常比赛/开球等)
    - ``DIRECT_FREE_KICK``:直接任意球(可直接射门得分)
    - ``INDIRECT_FREE_KICK``:间接任意球(须先触碰他人才能进球)
    - ``PENALTY_KICK``:点球
    - ``THROW_IN``:界外球(踢入)
    - ``GOAL_KICK``:球门球
    - ``CORNER_KICK``:角球
    """
    g = context.game
    if g is None:
        return SetPlay.NONE
    return g.set_play


# ======================================================================
# Agent 入口
# ======================================================================


class SoccerSimAgent(SoccerAgentMixin, AgentBase):
    """3v3 SoccerSim agent。"""

    player_class = Player

    def init_store(self, store) -> None:
        _log.info("init_store called")
        store.prev_phase = None       # 上一帧 phase,用于检测 phase 跳变(边沿)
        store.cur_phase = None
        store.kickoff_taker = None    # 锁定的开球主罚球员 id(每次进入开球时重选)
        store.normal_attacker = None
        store.normal_keeper = None
        store.set_play_taker = None   # 锁定的定位球主罚球员 id
        # v2.10:数据缺失防御。last_ball_pose 记住最后已知球位,ball 丢失时
        # 朝它慢走;data_loss_patrol 记录每台巡逻方向/换向时间,避免全员站死
        # 吃 inactiveRobot(第 4 场 7 张罚单的根因候选)。
        store.last_ball_pose = None
        store.data_loss_patrol = {}

    @staticmethod
    def play(context: Context, players: list[Player], store) -> None:
        phase = get_phase(context)
        store.prev_phase = store.cur_phase
        store.cur_phase = phase

        # 画可视化(每帧)
        _analyze_and_draw(context, players, store)

        # v2.10:记住最后已知球位。game/ball 短暂丢失时朝它慢走,不要全员站死。
        ball_now = context.ball
        if ball_now is not None:
            store.last_ball_pose = (ball_now.x, ball_now.y)

        # 当前 phase 以 label 画在场外。
        from .framework import debugdraw
        g = context.game
        # v2.16(Lead m02385):失球后 3s 内保持防守重心。用 GameControl 比分判定
        # 对手进球(防连续失球),窗口内 support 不许随球退进禁区。
        if g is not None:
            opp_score = None
            for team in g.teams:
                if int(team.team_number) != int(context.team_id):
                    opp_score = team.score
            prev_opp = getattr(store, "opp_score", None)
            if (
                prev_opp is not None
                and opp_score is not None
                and opp_score > prev_opp
            ):
                # v2.17(analyst): 失球后立刻进入 READY/SET,POST_CONCEDE_HOLD_S=3s
                # 会在 READY 内就过期(死代码)。改为挂 pending,等第一个 NORMAL
                # 帧(_act_normal)再开 3s 窗口,真正常规时间生效。
                store.post_concede_pending = True
            if opp_score is not None:
                store.opp_score = opp_score
        game_state = g.state.value if g is not None else "none"
        set_play = g.set_play.value if g is not None else "none"
        secondary_time = g.secondary_time if g is not None else 0.0
        debugdraw.text(
            0.0, context.field.width / 2.0 + 0.2,
            f"phase={phase.value} state={game_state} set={set_play} secondary={secondary_time:.1f}",
            rgb=(1.0, 1.0, 0.0), ns="phase",
        )

        # 活性自理 + 过滤出本帧可行动的球员。
        # ensure_ready:摔倒起身 / 切 walk 模式(异步,不产生移动);被罚下的也做,
        # 这样解罚后能立刻投入。被罚下或未就绪的不参与分派(也不进角色分配,避免把
        # 动不了的人选成 attacker 导致该帧无人进攻)。
        active: list[Player] = []
        for p in players:
            ready = p.ensure_ready()
            if p.is_penalized:
                p.action = "penalized"     # 罚下:可起身/切模式,但不能移动
                p.stop()
            elif not ready:
                if p.is_getting_up:
                    p.action = "getting_up"
                else:
                    p.action = "fallen" if p.is_fallen else "switching_mode"
            elif p.pose is None:
                p.action = "no_pose"       # 自己位置未知:不参与分派(下游按 pose 已知处理)
                p.stop()
            else:
                active.append(p)

        # 按 phase 对整队分派一次(角色分配等全队计算只在 _act_* 里算一次)。
        if phase == Phase.NORMAL:
            _act_normal(context, active, store)
        elif phase == Phase.OUR_KICKOFF:
            _clear_normal_sticky(store)
            _act_our_kickoff(context, active, store)
        elif phase == Phase.OPP_KICKOFF:
            _clear_normal_sticky(store)
            _act_opp_kickoff(context, active, store)
        elif phase == Phase.OUR_SET_PLAY:
            _clear_normal_sticky(store)
            _act_our_set_play(context, active, store)
        elif phase == Phase.OPP_SET_PLAY:
            _clear_normal_sticky(store)
            _act_opp_set_play(context, active, store)
        elif phase == Phase.READY:
            _clear_normal_sticky(store)
            _act_ready(context, active, store)
        elif phase == Phase.STOPPED:
            _clear_normal_sticky(store)
            _act_stopped(context, active, store)

        # 离开 READY 就丢弃槽位锁定,下次 READY 重新分配。
        if phase != Phase.READY:
            store.ready_assignment = None

        # 队员可视化统一在最后画一遍:覆盖所有球员(含判罚/未就绪/STOPPED),
        # 修复 SET 等状态下红球/标签消失的问题。
        for p in players:
            _draw_teammate_marker(p)


def _clear_normal_sticky(store) -> None:
    store.normal_attacker = None


def _player_dist_to_ball(context: Context, p: Player) -> float:
    """球员到球当前位置的距离。"""
    ball = context.ball
    return (
        dist(p.pose.x, p.pose.y, ball.x, ball.y) + _fallen_time_cost(p)
        if ball is not None else math.inf
    )


def _fallen_time_cost(p: Player) -> float:
    return FALLEN_COST if p.is_fallen else 0.0


def _select_closest_attacker(
    context: Context,
    players: list[Player],
    preferred_id: int | None = None,
) -> Player:
    """选到球距离最小的球员。

    ``players`` 非空、已就绪、pose 已知。normal 与开球共用。
    """
    ranked = [(p, _player_dist_to_ball(context, p)) for p in players]
    best, best_dist = min(ranked, key=lambda item: item[1])
    preferred = next((item for item in ranked if item[0].id == preferred_id), None)
    if (
        preferred is not None
        and preferred[1] <= best_dist + ATTACKER_KEEP_DIST_MARGIN_M
    ):
        return preferred[0]
    return best


def _field_point(
    context: Context, x: float, y: float, margin: float = 0.3,
) -> tuple[float, float]:
    """把目标点夹到场地内(留 margin 余量),避免机器人被赶出场。"""
    half_x = context.field.length / 2.0 - margin
    half_y = context.field.width / 2.0 - margin
    return clamp(x, -half_x, half_x), clamp(y, -half_y, half_y)


def _keep_clear_of_ball(context: Context, ball, target: tuple[float, float]) -> tuple[float, float]:
    """把目标点推到距球至少 SET_PLAY_DEF_GAP_M 的位置,再夹进场内。

    对方定位球期间,防守方机器人距球过近会在主罚触球瞬间被 R-07(1.45m)罚下,
    所以所有等待/站位目标都要留足余量。
    """
    bx, by = ball.x, ball.y
    tx, ty = target
    d = math.hypot(tx - bx, ty - by)
    if d < SET_PLAY_DEF_GAP_M:
        if d < 1e-6:
            ux, uy = -1.0, 0.0
        else:
            ux, uy = (tx - bx) / d, (ty - by) / d
        tx, ty = bx + ux * SET_PLAY_DEF_GAP_M, by + uy * SET_PLAY_DEF_GAP_M
    return _field_point(context, tx, ty, 0.3)


def _away_from_ball_point(
    context: Context, ball, pose, distance: float,
) -> tuple[float, float]:
    """从球指向 pose 的方向再外移 distance:已经太近时尽快撤离用。"""
    bx, by = ball.x, ball.y
    dx, dy = pose.x - bx, pose.y - by
    d = math.hypot(dx, dy)
    if d < 1e-6:
        ux, uy = -1.0, 0.0
    else:
        ux, uy = dx / d, dy / d
    return _field_point(context, bx + ux * distance, by + uy * distance, 0.3)


def _defender_set_play_spot(context: Context, ball, lateral: float) -> tuple[float, float]:
    """防守等待点:沿"球→己方门"方向后退 SET_PLAY_DEF_SAFE_DIST_M,并横向错开。"""
    gx, gy = own_goal(context)
    bx, by = ball.x, ball.y
    dx, dy = gx - bx, gy - by
    d = math.hypot(dx, dy)
    if d < 1e-6:
        ux, uy = -1.0, 0.0
    else:
        ux, uy = dx / d, dy / d
    px, py = -uy, ux    # 垂直于"球→门"方向
    tx = bx + ux * SET_PLAY_DEF_SAFE_DIST_M + px * lateral
    ty = by + uy * SET_PLAY_DEF_SAFE_DIST_M + py * lateral
    return _keep_clear_of_ball(context, ball, (tx, ty))


def _dist_point_to_line(
    px: float, py: float, ax: float, ay: float, bx: float, by: float,
) -> float:
    """点 (px,py) 到直线 ab 的垂直距离;ab 退化时返回点距 a 的距离。"""
    dx, dy = bx - ax, by - ay
    n = math.hypot(dx, dy)
    if n < 1e-6:
        return math.hypot(px - ax, py - ay)
    return abs(dx * (ay - py) - dy * (ax - px)) / n


def _set_play_kick_plan(
    context: Context, set_play: SetPlay, ball, taker_id: int | None = None,
    active_ids: set[int] | None = None,
) -> tuple[float, float]:
    """我方定位球:返回(场地系踢球方向, 力度)。

    - 角球:几何上无法直接射入,朝门前抢点位置传中;
    - 直接任意球/点球:直接打门;
    - 界外球/球门球/间接任意球:必须二次触球才允许进球,所以第一脚改成
      短传给最近的队友(队友触球=第二次触球),不要直接长传打门。
      (headless-04 实测 3 次 goal_disallowed_indirect:开球方一脚直接进球无效)

    v2.6:短传只考虑当前 active 队友(被罚下/未激活的不在 active_ids 里),
    落点禁止朝己方球门方向,力度按距离插值。线上 20c6a6cb 1:2 负的第 1 球
    就是界外球短传选中被罚下的 robot3、落点 (-5.8,3.0) 朝己门、固定 3.6 力度
    滚 8.2m 进自家门。
    """
    gx, gy = opponent_goal(context)
    half_length = context.field.length / 2.0
    if set_play in (SetPlay.CORNER_KICK, SetPlay.DIRECT_FREE_KICK, SetPlay.PENALTY_KICK):
        if set_play == SetPlay.CORNER_KICK:
            # 角球:传中到门前抢点区,别瞄门线(角度太偏,只会踢出底线送 goalKick)。
            target = (
                half_length - SET_PLAY_TARGET_MARGIN_M,
                clamp(ball.y * 0.15, -0.8, 0.8),
            )
            power = KICK_POWER_SET_PLAY_FORWARD
        else:
            target = (gx, gy)
            power = KICK_POWER_SET_PLAY_SHOT
    else:
        # 界外球/球门球/间接任意球:需二次触球才能进球。第一脚短传给合格队友;
        # 没有合格队友时退化为横向轻推。
        half_w = context.field.width / 2.0
        goal_line_limit = half_length - SET_PLAY_PASS_GOAL_LINE_GAP_M
        mate = None
        best = math.inf
        target = None
        for mate_id, mate_state in context.teammates.items():
            if mate_id == taker_id or mate_state.pose is None:
                continue
            if active_ids is not None and mate_id not in active_ids:
                continue
            d = dist(ball.x, ball.y, mate_state.pose.x, mate_state.pose.y)
            if d <= 0.8 or d >= best:
                continue
            # v2.20(analyst 第14场): 第一脚限距 5m——过远会被裁判视为「未完成
            # 二次触球」的间接球场景(551s 界外球 10.2m 直送对方半场,进球被吹)。
            if d > SET_PLAY_PASS_MAX_DIST_M:
                continue
            # v2.3:落点里收、避边线至少 1.2m,y 向中路拉,降低第一脚出界 retake。
            tx = clamp(mate_state.pose.x, -half_length + 1.2, half_length - 1.2)
            ty = mate_state.pose.y
            if abs(ty) > half_w - 1.5:
                ty = 0.6 * ty
            # v2.6:落点必须比球更靠前(球门方向),且不能深到己方半场深处。
            if ball.x < 4.0:
                tx = max(tx, ball.x + 1.0)
            tx = max(tx, -1.0)
            # v2.7:间接球第一脚不许直接/折射进门 —— 落点离对方门线至少 2m,
            # 且不能落在「球→对方门中心」的射门线上。
            tx = min(tx, goal_line_limit)
            tx = clamp(tx, -half_length + SET_PLAY_TARGET_MARGIN_M,
                       half_length - SET_PLAY_TARGET_MARGIN_M)
            ty = clamp(ty, -half_w + 1.2, half_w - 1.2)
            if _dist_point_to_line(tx, ty, ball.x, ball.y, gx, gy) < SET_PLAY_PASS_OFFLINE_M:
                continue
            # v2.14:落点必须离最近对手 >= SET_PLAY_PASS_OPP_CLEAR_M,避免第一脚
            # 直接传到被对手站住的中场(analyst 第 7 场:对方 7.66/7.98m/s 远射)。
            opp_clear = math.inf
            for opp in context.opponents.values():
                if opp.pose is None:
                    continue
                opp_clear = min(opp_clear, dist(tx, ty, opp.pose.x, opp.pose.y))
            if opp_clear < SET_PLAY_PASS_OPP_CLEAR_M:
                continue
            best = d
            mate = mate_state
            target = (tx, ty)
        if mate is not None:
            pass_dist = dist(ball.x, ball.y, target[0], target[1])
            power = clamp(
                SET_PLAY_PASS_POWER_BASE + SET_PLAY_PASS_POWER_PER_M * pass_dist,
                SET_PLAY_PASS_POWER_MIN,
                SET_PLAY_PASS_POWER_MAX,
            )
        else:
            # v2.8:横向轻推只在球已过半场附近(ball.x > -2)时用。复盘
            # 60d19472:52.44s 我方门球第一脚从 (-6.00,-2.00) 横穿自家球门口
            # 送到 (-6.97,+2.18),直接送对方角球;己方三区改为向前 2m、偏同侧
            # 的解围方向轻推(仍不朝对方门线)。
            if ball.x > -2.0:
                push_y = ball.y + (2.0 if ball.y <= 0.0 else -2.0)
                target = (ball.x, clamp(push_y, -half_w + 1.2, half_w - 1.2))
            else:
                side = 1.0 if ball.y >= 0.0 else -1.0
                target = (
                    clamp(ball.x + 2.0, -half_length + SET_PLAY_TARGET_MARGIN_M,
                          goal_line_limit),
                    clamp(ball.y + side * 1.5, -half_w + 1.2, half_w - 1.2),
                )
            power = SET_PLAY_LATERAL_POWER
    return angle_to(ball.x, ball.y, target[0], target[1]), power


def _ball_velocity_mps(
    context: Context, store,
) -> tuple[float, float] | None:
    """用上一帧球位置差分估算球速向量(m/s);首帧或断帧返回 None。"""
    ball = context.ball
    if ball is None:
        return None
    prev = getattr(store, "ball_prev", None)
    store.ball_prev = (ball.x, ball.y, context.now)
    if prev is None:
        return None
    dt = context.now - prev[2]
    if dt <= 1e-3 or dt > 0.5:
        return None
    return (ball.x - prev[0]) / dt, (ball.y - prev[1]) / dt


def _ball_speed_mps(context: Context, store) -> float | None:
    """用上一帧球位置差分估算球速(m/s);首帧或断帧返回 None。"""
    vel = _ball_velocity_mps(context, store)
    if vel is None:
        return None
    return math.hypot(vel[0], vel[1])


def _slow_patrol(
    context: Context, p: Player, store, ball_xy: tuple[float, float] | None,
) -> None:
    """v2.10:数据缺失(game/ball 为 None)时的防御性慢速巡逻,替代全员硬停。

    线上第 4 场(f751146f 0:6)288–305s:我方三台机器人同时 0 指令、距球 0.31m
    的 robot1 站了 10s+ → 3 张 inactiveRobot。按 Lead 指示:数据缺失 ≠ 裁判
    要求静止。这里用 0.12m/s 小幅巡逻(2s 换向,任意 2s 窗口位移 ≤0.24m,低于
    M-02 的 0.3m 阈值;球位已知时沿「远离最后球位」的径向走,满足 R-07 的
    径向远离要求),让平台判定机器人在活动,同时不会在真实 SET 期超阈值移动。
    """
    if p.pose is None:
        p.action = "data_loss:no_pose"
        p.stop()
        return
    state = getattr(store, "data_loss_patrol", None)
    if state is None:
        state = {}
        store.data_loss_patrol = state
    now = context.now
    item = state.get(p.id)
    if item is None:
        item = [1.0, now + DATA_LOSS_PATROL_FLIP_S]
        state[p.id] = item
    sign, next_flip = item[0], item[1]
    if now >= next_flip:
        sign = -sign
        item[0] = sign
        item[1] = now + DATA_LOSS_PATROL_FLIP_S
    step = DATA_LOSS_PATROL_STEP_M
    if ball_xy is not None:
        dx, dy = p.pose.x - ball_xy[0], p.pose.y - ball_xy[1]
        norm = math.hypot(dx, dy)
        if norm > 1e-6:
            ux, uy = dx / norm, dy / norm
            tx = p.pose.x + ux * step
            ty = p.pose.y + uy * step + sign * 0.25
        else:
            tx, ty = p.pose.x + sign * step, p.pose.y
    else:
        # 无球位参照:沿场地长轴来回小幅移动。
        tx, ty = p.pose.x + sign * step, p.pose.y
    p.action = "data_loss:patrol"
    p.omni_move_toward(
        _field_point(context, tx, ty, 0.4), speed=DATA_LOSS_PATROL_SPEED,
    )


def _act_normal(context: Context, players: list[Player], store) -> None:
    """NORMAL:距球最近者 attack,剩下人里离己方门最近者 guard,其余 support。

    ``players`` 是本帧可行动球员(已就绪、pose 已知),这里直接挑角色并执行。
    """
    if not players:
        return

    # v2.10:球信息丢失(约 1.5s 没更新)不等于全员站死。第 4 场 f751146f
    # 288–305s 我方三台同时 0 指令、距球 0.31m 的人站 10s+ → 3 张 inactiveRobot。
    # 这里改为:门将回门前慢速巡逻;其他人朝最后已知球位慢走近(补位/施压),
    # 到位后转入慢速巡逻,保证「球在 3m 内但一直不动」不会发生。
    if context.ball is None:
        last = getattr(store, "last_ball_pose", None)
        keeper_id = getattr(store, "normal_keeper", None)
        for p in players:
            if p.id == keeper_id:
                _slow_patrol(context, p, store, last)
                continue
            if (
                last is not None
                and p.pose is not None
                and dist(p.pose.x, p.pose.y, last[0], last[1])
                > DATA_LOSS_APPROACH_M
            ):
                p.action = "no_ball:approach"
                p.omni_move_toward(
                    _field_point(context, last[0], last[1], 0.4),
                    speed=DATA_LOSS_PATROL_SPEED,
                )
            else:
                _slow_patrol(context, p, store, last)
        return

    # v2.10 紧急修复(analyst 2026-11-23 定位):v2.7 的 presser 分支引用了未定义的
    # 局部变量 ball,导致「球一停(球速<0.2m/s)」时 play() 每帧抛 NameError,
    # runtime 捕获后对全员 p.stop() → 全队冻结、近球站 10s+ 吃 inactiveRobot
    # (v2.7 第 3 场 0:6、v2.8 第 4 场 0:6、v2.9 第 5 场 9 张罚单均由此引起)。
    ball = context.ball
    if ball is None:  # 理论不可达(上面的 None 分支已 return),防御性收窄类型
        return
    # v2.17: 失球后的防守窗口从「进入 NORMAL 的第一帧」起算(README/SET 不算)。
    if getattr(store, "post_concede_pending", False):
        store.defend_hold_until = context.now + POST_CONCEDE_HOLD_S
        store.post_concede_pending = False

    # v2.0 协同分工:先固定 1 台门将(离己方门最近),绝不让门将参与抢球;
    # 剩下两人里离球最近者当 primary(抢/带/射),最后一人当 support(接应/保护)。
    # 旧实现「离球最近者 attack,其余里离己方门最近者 guard」在结构上允许门将
    # 被选为 attacker 而离门出击(线上 replay 已看到门前无人),这里先锁门将。
    gx, gy = own_goal(context)
    keeper = min(players, key=lambda p: dist(p.pose.x, p.pose.y, gx, gy))
    # v2.5:门将粘滞。线上 v2.4(0:5)复盘发现门将角色在两台深位机器人之间反复
    # 切换,两人都往门前挤/互相推挤,导致门线出现空档。这里保留上一帧门将,除非
    # 它已明显离门更远(>1.5m)。
    # v2.11:本段在 v2.5 引入时漏了 store 形参(调用处也没传),导致每次
    # OPP_KICKOFF 每帧抛 NameError → runtime 全员 stop;analyst 用回放自检抓到。
    prev_keeper_id = getattr(store, "normal_keeper", None)
    if prev_keeper_id is not None:
        prev_keeper = next((p for p in players if p.id == prev_keeper_id), None)
        if prev_keeper is not None:
            d_prev = dist(prev_keeper.pose.x, prev_keeper.pose.y, gx, gy)
            d_best = dist(keeper.pose.x, keeper.pose.y, gx, gy)
            if d_prev <= d_best + 1.5:
                keeper = prev_keeper
    store.normal_keeper = keeper.id
    field_players = [p for p in players if p is not keeper]
    attacker: Player | None = None
    primary_pose: tuple[float, float] | None = None
    rest: list[Player] = []
    # v2.7:活球「站桩」修复(P0)。线上复盘:球速≈0、我方非门将无人进 1.2m 时
    # 常没人去抢(最近者 0.7-0.9m 却因绕球/角色停在旁边),白给对手断球。这里
    # 在开放球权 + 球几乎静止 + 无人贴近时,强制最近的非门将做 presser。
    game = context.game
    speed = _ball_speed_mps(context, store)
    forced_presser: Player | None = None
    if (
        field_players
        and speed is not None
        and speed < PRESSER_STALL_SPEED_MPS
        and game is not None
        and game.state == GameState.PLAYING
        and not game.stopped
        and (game.set_play is None or game.set_play == SetPlay.NONE)
    ):
        near = min(
            field_players, key=lambda q: dist(q.pose.x, q.pose.y, ball.x, ball.y),
        )
        chosen = near
        # v2.17(analyst 第11场): presser 粘滞 1s,避免 distance 排序换人导致
        # 「手递手」浪费 0.3–0.5s(第11场 G1/G3 presser 交接)。
        prev_id = getattr(store, "presser_id", None)
        if getattr(store, "presser_until", 0.0) > context.now and prev_id is not None:
            prev = next((q for q in field_players if q.id == prev_id), None)
            if prev is not None:
                chosen = prev
        if (
            dist(chosen.pose.x, chosen.pose.y, ball.x, ball.y)
            > PRESSER_TRIGGER_DIST_M
        ):
            forced_presser = chosen
    if forced_presser is not None:
        attacker = forced_presser
        store.normal_attacker = attacker.id
        store.presser_id = attacker.id
        store.presser_until = context.now + PRESSER_HOLD_S
        # v2.12(P0-a): 己方三区死球不再绕位,直接站到球的门侧再解围。第 7 场
        # sim 148.31/554.53 两失球同型:三区静止球,我方最近者绕位 1.5s 不触球,
        # 对手 0.35m 先捅;解围方向朝对方半场边线(不在门前横传)。
        if (
            ball is not None
            and speed is not None
            and ball.x < OWN_THIRD_CLEAR_BALL_X
            and speed < PRESSER_STALL_SPEED_MPS
        ):
            gx, gy = own_goal(context)
            ux, uy = gx - ball.x, gy - ball.y
            un = math.hypot(ux, uy)
            if un > 1e-6:
                ux, uy = ux / un, uy / un
            else:
                ux, uy = -1.0, 0.0
            ax = ball.x + PRESSER_DEADBALL_APPROACH_M * ux
            ay = ball.y + PRESSER_DEADBALL_APPROACH_M * uy
            d_ball = (
                dist(attacker.pose.x, attacker.pose.y, ball.x, ball.y)
                if attacker.pose is not None
                else 99.0
            )
            if d_ball > PRESSER_KICK_DIST_M:
                # v2.17(analyst): 1.6m/s omni 直冲门侧点,不再按 walk_to 低速绕行。
                attacker.action = "pressing:clear_approach"
                attacker.omni_move_toward(
                    _field_point(context, ax, ay, 0.4),
                    speed=PRESSER_APPROACH_SPEED_MPS,
                )
            else:
                side = 1.0 if ball.y >= 0.0 else -1.0
                half_w = context.field.width / 2.0
                attacker.action = "pressing:clear"
                attacker.kick(
                    angle_to(ball.x, ball.y, 0.0, side * (half_w - 1.2)),
                    KICK_POWER_CLEAR,
                )
        else:
            attacker.action = "pressing"
            attacker.attack()
        if attacker.pose is not None:
            primary_pose = (attacker.pose.x, attacker.pose.y)
        rest = [p for p in field_players if p is not attacker]
    elif field_players:
        attacker = _select_closest_attacker(
            context, field_players, getattr(store, "normal_attacker", None),
        )
        store.normal_attacker = attacker.id
        attacker.action = "attack"
        attacker.attack()
        if attacker.pose is not None:
            primary_pose = (attacker.pose.x, attacker.pose.y)
        rest = [p for p in field_players if p is not attacker]

    keeper.action = "guard"
    keeper.guard()

    # v2.16(Lead m02385):失球后 3s 内 support 保持中场防守线(x≥-2.0),
    # 不随球退进禁区;primary 照常追球,门将照常守门,避免连续失球。
    hold_until = getattr(store, "defend_hold_until", 0.0)
    holding = context.now < hold_until
    for p in rest:
        if holding and p.pose is not None and p.pose.x < POST_CONCEDE_MIN_X:
            p.action = "support:hold_line"
            hy = clamp(ball.y * 0.4, -2.5, 2.5)
            p.move_to_position((POST_CONCEDE_MIN_X, hy))
            continue
        p.action = "support"
        p.support(primary_pose)


def _act_our_kickoff(context: Context, players: list[Player], store) -> None:
    """OUR_KICKOFF:锁定距离最小者开球,剩下人里离己方门最近者 guard,其余原地等待。

    开球不触发自由球避让(is_free_kick 不含 kickOff),非主罚方只需"本方半场 + 圈外";
    我方非主罚球员此时不动最稳。
    """
    if not players:
        return

    active_ids = {p.id for p in players}
    if store.prev_phase != Phase.OUR_KICKOFF or store.kickoff_taker not in active_ids:
        # 进入开球阶段，重新选择开球球员
        store.kickoff_taker = _select_closest_attacker(context, players).id

    attacker_id = store.kickoff_taker
    attacker = next((p for p in players if p.id == attacker_id), None)
    if attacker is None:
        return

    attacker.action = "kickoff"
    # 开球第一脚必须短传/带球,不能直接射门:G-05 要求开球方开球后进球需
    # 「≥2 台机器人触球」或「触球点距开球点>0.5m」,直接射门进球会被判无效
    # （headless-06 +148.3s goal_disallowed_kickoff 实测）。这里把球短传给
    # 最近的队友,队友触球即完成第二次触球;之后正常进攻再射门就合法。
    ball = context.ball
    receiver = None
    best = math.inf
    for mate in players:
        if mate is attacker or mate.pose is None:
            continue
        bx, by = (ball.x, ball.y) if ball is not None else (0.0, 0.0)
        d = dist(bx, by, mate.pose.x, mate.pose.y)
        if d < best:
            best = d
            receiver = mate
    if receiver is not None and ball is not None and best > 0.5:
        kick_dir = angle_to(ball.x, ball.y, receiver.pose.x, receiver.pose.y)
        attacker.kick(kick_dir, KICK_POWER_OUR_KICKOFF_PASS)
    else:
        # 没有可传队友时的兜底:侧向轻推,避免直接打门被判无效。
        side = 1.0 if attacker.id % 2 == 0 else -1.0
        attacker.kick(angle_to(0.0, 0.0, -1.0, side * 1.5), KICK_POWER_OUR_KICKOFF_PASS)

    rest = [p for p in players if p is not attacker]
    if rest:
        gx, gy = own_goal(context)
        guard = min(rest, key=lambda p: dist(p.pose.x, p.pose.y, gx, gy))
        guard.guard()
        rest = [p for p in rest if p is not guard]

    # 非主罚球员必须在本方半场且中圈外。旧版直接 stop() 原地不动,若球权转换前
    # 人还在对方半场/中线附近,开球瞬间就吃 kickoff_kicking_side_outside_center
    # (iteration-10 实测 robot1 robotX=0.06、robot2 robotX=1.57,各 30s)。
    # v2.9:第 4 场 f751146f 7 张 inactiveRobot 根因——开球期非主罚"原地 stay",
    # 主罚触球后球滚到脚边 0.31m 停住,10s 内累计 inactive 被罚下。改为每帧
    # 检查威胁:球 3.2m 内或球正向我方半场滚动 → 立刻退到安全点并保持走位,
    # 不再 stop 站桩(安全点仍在己方半场、中圈外,满足开球站位规则)。
    vel = _ball_velocity_mps(context, store)
    ball_toward_half = (
        vel is not None and vel[0] < KICKOFF_BALL_TOWARD_HALF_VX
    )
    for idx, p in enumerate(rest):
        if p.pose is None:
            p.action = "stay"
            p.stop()
            continue
        if ball is None:
            # v2.10:球信息丢失时不站死,慢速巡逻等球重新出现。
            _slow_patrol(context, p, store, getattr(store, "last_ball_pose", None))
            continue
        d_ball = dist(p.pose.x, p.pose.y, ball.x, ball.y)
        if d_ball < KICKOFF_STAY_SAFE_DIST_M or ball_toward_half:
            # 选离球更远的一侧;安全点仍在球 3.2m 内则退到更深的一档。
            side = (
                1.0
                if abs(ball.y - KICKOFF_SAFE_Y)
                > abs(ball.y + KICKOFF_SAFE_Y)
                else -1.0
            )
            sx = KICKOFF_SAFE_X
            sy = side * KICKOFF_SAFE_Y
            if dist(ball.x, ball.y, sx, sy) < KICKOFF_STAY_SAFE_DIST_M:
                sx = KICKOFF_DEEP_SAFE_X
                sy = side * KICKOFF_DEEP_SAFE_Y
            target = _field_point(context, sx, sy, 0.3)
            p.action = "kickoff:clear_stay"
            p.walk_to(
                target, face=0.0, avoid_ball=False, avoid_robots=True,
            )
            continue
        target = _field_point(
            context, -1.0, 2.4 if idx % 2 == 0 else -2.4, 0.3,
        )
        needs_reposition = (
            p.pose.x > -0.3
            or dist(p.pose.x, p.pose.y, 0.0, 0.0)
            < context.field.circle_radius + 0.2
        )
        if needs_reposition:
            p.action = "kickoff:reposition"
            p.walk_to(
                target, face=0.0, avoid_ball=False, avoid_robots=True,
            )
        else:
            p.action = "stay"
            p.stop()


def _act_opp_kickoff(
    context: Context, players: list[Player], store,
) -> None:
    """对方开球:门将守门,其余人站本方半场、中圈外、距球 >3m 的等待点。

    规则:开球不触发自由球避让(is_free_kick 不含 kickOff),但非开球方
    (a) 必须在本方半场 (b) 不得进中圈(离中心 >1.55m)。等待点再留离球 >3m,
    避开 M-05(球 3m 内 10s 不动罚下)。
    """
    if not players:
        return
    gx, gy = own_goal(context)
    keeper = min(players, key=lambda p: dist(p.pose.x, p.pose.y, gx, gy))
    # v2.5:门将粘滞。线上 v2.4(0:5)复盘发现门将角色在两台深位机器人之间反复
    # 切换,两人都往门前挤/互相推挤,导致门线出现空档。这里保留上一帧门将,除非
    # 它已明显离门更远(>1.5m)。
    # v2.11:本段在 v2.5 引入时漏了 store 形参(调用处也没传),导致每次
    # OPP_KICKOFF 每帧抛 NameError → runtime 全员 stop;analyst 用回放自检抓到。
    prev_keeper_id = getattr(store, "normal_keeper", None)
    if prev_keeper_id is not None:
        prev_keeper = next((p for p in players if p.id == prev_keeper_id), None)
        if prev_keeper is not None:
            d_prev = dist(prev_keeper.pose.x, prev_keeper.pose.y, gx, gy)
            d_best = dist(keeper.pose.x, keeper.pose.y, gx, gy)
            if d_prev <= d_best + 1.5:
                keeper = prev_keeper
    store.normal_keeper = keeper.id
    keeper.action = "opp_kickoff:keeper"
    keeper.guard()
    rest = [p for p in players if p is not keeper]

    ball = context.ball
    bx, by = (ball.x, ball.y) if ball is not None else (0.0, 0.0)
    dx, dy = gx - bx, gy - by
    d = math.hypot(dx, dy)
    ux, uy = (dx / d, dy / d) if d > 1e-6 else (-1.0, 0.0)
    px, py = -uy, ux

    for i, p in enumerate(rest):
        lateral = 1.4 if i % 2 == 0 else -1.4
        tx = bx + ux * OPP_KICKOFF_WAIT_RADIUS_M + px * lateral
        ty = by + uy * OPP_KICKOFF_WAIT_RADIUS_M + py * lateral
        # 非开球方必须在本方半场(x<=0),同时留一点余量。
        tx = min(tx, -0.15)
        tx, ty = _field_point(context, tx, ty, 0.3)
        # 兜底:万一半场约束把点拉近中心圈,再沿径向推到圈外。
        cx, cy = tx - bx, ty - by
        cd = math.hypot(cx, cy)
        if cd < 1.75:
            if cd < 1e-6:
                tx, ty = min(bx, 0.0) - 1.75, by
            else:
                tx, ty = bx + cx / cd * 1.75, by + cy / cd * 1.75
            tx = min(tx, -0.15)
            tx, ty = _field_point(context, tx, ty, 0.3)
        p.action = "opp_kickoff:wait"
        p.walk_to((tx, ty), face=0.0, avoid_ball=False, avoid_robots=True)


def _act_our_set_play(context: Context, players: list[Player], store) -> None:
    """OUR_SET_PLAY:我方定位球。摆球(stopped)时全员静止,球放开后主罚按类型踢球。

    规则要点:
    - 摆球阶段全员必须静止,不许碰球;
    - 界外球/球门球/间接任意球:进球前需要 2 次触球(或球离开开球点 0.5m),
      所以第一脚向前踢、由队友或自身第二次触球后再射门;
    - 角球/直接任意球/点球:可以直接射门;
    - 我方所有定位球第一脚都不许朝己方门(否则乌龙无效+对方角球)。
    """
    g = context.game
    set_play = get_set_play_type(context)

    if g is not None and g.stopped:
        # v2.10 审计:这是裁判明确 stopped=True 的摆球期,静止是规则要求;
        # 与「game/ball 数据缺失」不同,这里必须真停,不能改成慢速巡逻。
        for p in players:
            p.action = "setplay:placement"
            p.stop()
        return

    if not players:
        return
    ball = context.ball
    if ball is None:
        # v2.10:球信息丢失也不全员站死(旧逻辑 stop() 会在球旁累积
        # inactiveRobot),改为朝最后已知球位慢速巡逻。
        last = getattr(store, "last_ball_pose", None)
        for p in players:
            _slow_patrol(context, p, store, last)
        return

    # 主罚选择:阶段内粘滞避免抖动。
    if store.prev_phase != Phase.OUR_SET_PLAY:
        store.set_play_taker = None
        store.ready_assignment = None
    # v2.6:不再只选「离球最近」,改为「到球后方接近点(ball-kick_dir*1.0)最近」
    # 者优先并排除门将:线上 20c6a6cb 多次 12-32s 才完成第一脚,贴边线球
    # 最近者常绕不过来。probe 计划只用来自算 kick_dir,真正踢球方向下面重算。
    active_ids = {p.id for p in players}
    gx, gy = own_goal(context)
    keeper = min(players, key=lambda q: dist(q.pose.x, q.pose.y, gx, gy))
    candidates = [q for q in players if q is not keeper] or players
    probe_dir, _ = _set_play_kick_plan(context, set_play, ball, None, active_ids)
    approach_x = ball.x - math.cos(probe_dir) * SET_PLAY_TAKER_APPROACH_M
    approach_y = ball.y - math.sin(probe_dir) * SET_PLAY_TAKER_APPROACH_M
    taker = min(
        candidates,
        key=lambda q: dist(q.pose.x, q.pose.y, approach_x, approach_y),
    )
    prev_taker = getattr(store, "set_play_taker", None)
    if prev_taker is not None and prev_taker != taker.id:
        prev_p = next((q for q in candidates if q.id == prev_taker), None)
        if prev_p is not None and dist(
            prev_p.pose.x, prev_p.pose.y, approach_x, approach_y
        ) <= dist(taker.pose.x, taker.pose.y, approach_x, approach_y) + SET_PLAY_TAKER_KEEP_MARGIN_M:
            taker = prev_p
    store.set_play_taker = taker.id
    rest = [p for p in players if p is not taker]

    kick_dir, power = _set_play_kick_plan(context, set_play, ball, taker.id, active_ids)
    taker.action = f"setplay:{set_play.value}"
    if dist(taker.pose.x, taker.pose.y, ball.x, ball.y) > SET_PLAY_NEAR_BALL_M:
        # 先绕到球的"踢球侧"(贴边线时会被夹进场内,足够接近后下一帧直接踢)。
        approach = _field_point(
            context,
            ball.x - math.cos(kick_dir) * SET_PLAY_TAKER_APPROACH_M,
            ball.y - math.sin(kick_dir) * SET_PLAY_TAKER_APPROACH_M,
            0.3,  # v2.15:绕行目标留 0.3m 场内余量(analyst 提醒)
        )
        # v2.14:avoid_ball=False(analyst+Lead:绕开球会让主罚多绕 1-2s 才触球,
        # 线上第 7 场定位球首触中位 12.2s;接近点已缩到 0.5m,直接走向球更稳)。
        taker.walk_to(approach, face=kick_dir, avoid_ball=False)
    else:
        taker.kick(kick_dir, power)

    # 剩下人:离己方门最近者回守护门,其余人前插准备接应(不碰球)。
    if rest:
        gx, gy = own_goal(context)
        keeper = min(rest, key=lambda p: dist(p.pose.x, p.pose.y, gx, gy))
        keeper.action = "setplay:guard"
        keeper.guard()
        rest = [p for p in rest if p is not keeper]

    half_length = context.field.length / 2.0
    half_width = context.field.width / 2.0
    for i, p in enumerate(rest):
        p.action = "setplay:receive"
        tx = min(ball.x + SET_PLAY_RECEIVER_AHEAD_M, half_length - 0.6)
        ty = clamp(ball.y + (1.2 if i % 2 == 0 else -1.2), -half_width + 0.6, half_width - 0.6)
        p.move_to_position(_field_point(context, tx, ty, 0.35))


def _act_opp_set_play(context: Context, players: list[Player], store) -> None:
    """对方定位球:主罚触球(ball_free)之前,全员距球 >1.45m 且不碰球。

    规则要点:
    - 防守方在主罚触球前触球 → R-06 罚下 30s 并重踢;
    - 主罚触球瞬间防守方距球 <1.45m → R-07 罚下 30s 并重踢;
    - 球在 3m 内站 10s 不动 → M-05 罚下,所以等待点放在 3.3m 外;
    - 绝对不能调用 attack/kick,也不能进中圈或对方半场之外的禁区风险区。
    等官方状态 set_play 清空(ball_free)后,下一帧自动切回 NORMAL 再抢。
    """
    if not players:
        return
    # 摆球阶段(referee stopped=True)必须全静止:此时任何移动都可能被判
    # motionInSet(30s);get_phase 一般已把 stopped 路由到 _act_stopped,
    # 这里再兜底一次,避免 phase 判定竞态造成的摆球期移动。
    g = context.game
    if g is not None and g.stopped:
        # v2.10 审计:这是裁判明确 stopped=True 的摆球期,静止是规则要求;
        # 与「game/ball 数据缺失」不同,这里必须真停,不能改成慢速巡逻。
        for p in players:
            p.action = "setplay:placement"
            p.stop()
        return
    ball = context.ball
    if ball is None:
        # v2.10:同上,数据缺失≠裁判暂停,慢速巡逻避免 inactiveRobot。
        last = getattr(store, "last_ball_pose", None)
        for p in players:
            _slow_patrol(context, p, store, last)
        return

    gx, gy = own_goal(context)
    half_length = context.field.length / 2.0

    # 门将:常规回小禁区;球太近时退到门线一侧并继续留出避让余量。
    keeper = min(players, key=lambda p: dist(p.pose.x, p.pose.y, gx, gy))
    rest = [p for p in players if p is not keeper]
    if dist(keeper.pose.x, keeper.pose.y, ball.x, ball.y) < SET_PLAY_DEF_GAP_M + 0.3:
        ky = clamp(ball.y * 0.3, -KEEPER_GOAL_LINE_Y_LIMIT_M, KEEPER_GOAL_LINE_Y_LIMIT_M)
        keeper_target = _keep_clear_of_ball(
            context,
            ball,
            (-(half_length - KEEPER_GOAL_LINE_INSET_M), ky),
        )
        if dist(keeper.pose.x, keeper.pose.y, ball.x, ball.y) < RESTART_AVOID_RADIUS_M + 0.8:
            keeper.action = "opp_setplay:keeper_escape"
            keeper.omni_move_toward(keeper_target)
        else:
            keeper.action = "opp_setplay:keeper_fallback"
            keeper.walk_to(
                keeper_target,
                face=angle_to(keeper.pose.x, keeper.pose.y, ball.x, ball.y),
                avoid_ball=False,
                avoid_robots=True,
            )
    else:
        keeper.action = "opp_setplay:keeper"
        keeper.guard()

    laterals = (-1.2, 1.2)
    for i, p in enumerate(rest):
        d_ball = dist(p.pose.x, p.pose.y, ball.x, ball.y)
        target = _defender_set_play_spot(context, ball, laterals[i % len(laterals)])
        if d_ball < SET_PLAY_DEF_RADIAL_PULL_DIST_M:
            # v2.15:已进入 R-07(1.45m)红线外侧缓冲带:先纯径向退到 3.1m。
            # v2.16:弦线下界只在起点在圆上时成立(analyst m02284),1.7–2.4m
            # 起步先纯径向拉到 3.1m 再切向转;贴边/角旗被 clamp 得更近时改切向
            # 撤离,绝不朝球移动。
            target = _away_from_ball_point(
                context, ball, p.pose, SET_PLAY_DEF_ORBIT_RADIUS_M
            )
            ex, ey = _field_point(context, target[0], target[1], 0.3)
            d_escape = dist(ex, ey, ball.x, ball.y)
            if d_escape < max(SET_PLAY_DEF_MIN_CLEAR_M, d_ball + 0.05):
                ux, uy = (p.pose.x - ball.x) / max(d_ball, 1e-6), (
                    p.pose.y - ball.y
                ) / max(d_ball, 1e-6)
                best = None
                for sgn in (1.0, -1.0):
                    cx = ball.x + (-uy) * sgn * SET_PLAY_DEF_ORBIT_RADIUS_M
                    cy = ball.y + (ux) * sgn * SET_PLAY_DEF_ORBIT_RADIUS_M
                    cx, cy = _field_point(context, cx, cy, 0.3)
                    cd = dist(cx, cy, ball.x, ball.y)
                    if best is None or cd > best[0]:
                        best = (cd, cx, cy)
                _, ex, ey = best
            p.action = "opp_setplay:radial_escape"
            p.omni_move_toward((ex, ey))
        elif d_ball < SET_PLAY_DEF_SAFE_DIST_M:
            # v2.15:径向先行 + 逐帧闭环。第 9 场 d1ebca78 两张罚单的根因是
            # 从摆球期位置直线走向「球对侧」等待点时路径穿球(R-06 触球 /
            # R-07 1.005m)。这里改为在「以球心为圆心、半径 3.1m」的圆弧上
            # 朝等待点方向逐步旋转(每帧 ≤0.55rad),弦线离球最近 2.98m。
            # v2.16:半径 2.6→3.1 避开 M-05(球距≤3m 且 10s 几乎不动会吃
            # inactiveRobot);到位后按 2.5s 周期 ±0.2rad 微摆作双保险。
            ux, uy = (p.pose.x - ball.x) / d_ball, (p.pose.y - ball.y) / d_ball
            wx, wy = target[0] - ball.x, target[1] - ball.y
            wn = math.hypot(wx, wy)
            if wn < 1e-6:
                p.action = "opp_setplay:wait"
                p.move_to_position(target)
                continue
            a_pose = math.atan2(uy, ux)
            a_wait = math.atan2(wy / wn, wx / wn)
            step = clamp(normalize_angle(a_wait - a_pose), -0.55, 0.55)
            a = a_pose + step
            if abs(step) < 0.05:
                # 已贴近等待角:轻微往返摆动,避免 10s 完全静止触发 M-05。
                flip = int(context.now / SET_PLAY_DEF_ORBIT_SHUFFLE_PERIOD_S) % 2
                a += (
                    SET_PLAY_DEF_ORBIT_SHUFFLE_RAD
                    if flip == 0
                    else -SET_PLAY_DEF_ORBIT_SHUFFLE_RAD
                )
            tx = ball.x + math.cos(a) * SET_PLAY_DEF_ORBIT_RADIUS_M
            ty = ball.y + math.sin(a) * SET_PLAY_DEF_ORBIT_RADIUS_M
            ox, oy = _field_point(context, tx, ty, 0.3)
            if dist(ox, oy, ball.x, ball.y) < SET_PLAY_DEF_MIN_CLEAR_M:
                # 贴边/角球时圆弧点会被夹进场内(离球变近),退回径向撤离。
                target = _away_from_ball_point(
                    context, ball, p.pose, SET_PLAY_DEF_ORBIT_RADIUS_M
                )
                p.action = "opp_setplay:radial_escape"
                p.omni_move_toward(target)
            else:
                p.action = "opp_setplay:orbit"
                p.omni_move_toward((ox, oy))
        else:
            p.action = "opp_setplay:wait"
            p.move_to_position(target)


def _act_stopped(context: Context, players: list[Player], store) -> None:
    """STOPPED:SET/摆球等必须静止的阶段。

    例外是对方定位球的摆球阶段:裁判给 1.5s 刹车宽限期,宽限内把仍贴近球的
    机器人撤出 1.45m 风险圈,否则主罚触球瞬间吃 R-07(v2.1 线上 0:1 就因此丢球+罚下)。
    v2.6:线上 20c6a6cb(1:2 负)3 张 stopped_motion(sim 204/521/670s,0.301-0.330m)
    的根因是窗口结束后这里只 `continue` 不发命令,机器人保留上一帧速度指令滑行;
    现在:①记录 stopped_since 时回拨 0.35s 补偿 GameControl 发布延迟;②窗口
    0.35s、速度 1.0m/s;③只撤离「距球 <1.8m 的我方非门将」;④窗口结束后撤离
    名单不再硬停(v2.7:硬停到主罚触球会吃 R-07),改为 0.12m/s 径向慢爬,其余
    球员显式 p.stop(),目标摆球期 0 罚单。
    我方定位球摆球时不移动;SET 阶段一律静止。
    """
    g = context.game
    if g is None:
        # v2.10:收不到裁判状态 ≠ 裁判要求静止。旧逻辑全员 stop(),一旦
        # game/ball 数据短暂丢失就三台一起站死(第 4 场 288–305s 的 7 张
        # inactiveRobot)。只有 game 存在且明确 stopped=True / SET 时才是
        # 真静止(见下方),这里改为慢速巡逻,避免球旁机器人 10s 不动被罚。
        last = getattr(store, "last_ball_pose", None)
        for p in players:
            _slow_patrol(context, p, store, last)
        return

    if store.prev_phase != Phase.STOPPED:
        # v2.6:-0.35s 补偿裁判状态的发布延迟,让宽限窗口对齐真实计时点。
        store.stopped_since = context.now - STOP_STATE_LATENCY_COMP_S
        # v2.16:记录「我方首次检测到 stopped」的时刻,用于双段撤离的早段判定。
        store.stopped_detect_at = context.now
    elapsed = context.now - getattr(store, "stopped_since", context.now)
    elapsed_detect = context.now - getattr(store, "stopped_detect_at", context.now)

    our_team = context.team_id
    defending_restart = (
        g.state == GameState.PLAYING
        and g.stopped
        and g.set_play != SetPlay.NONE
        and g.kicking_team is not None
        and int(g.kicking_team) != int(KICKING_TEAM_NONE)
        and int(g.kicking_team) != int(our_team)
    )
    ball = context.ball
    # v2.6:门将不参与撤离(vacate 会把它从门线上拉走),宁可让门将静止。
    keeper_id = None
    if players:
        gx, gy = own_goal(context)
        keeper_id = min(
            players, key=lambda q: dist(q.pose.x, q.pose.y, gx, gy)
        ).id

    for p in players:
        if (
            defending_restart
            and ball is not None
            and p.pose is not None
            and p.id != keeper_id
        ):
            d_ball = dist(p.pose.x, p.pose.y, ball.x, ball.y)
            # v2.15:触发 1.8→2.3m、撤离目标 2.0→2.6m(analyst 第 9 场复盘:
            # 摆在 1.8-2.3m 的机器人主罚触球瞬间常在 1.45m 红线附近)。
            if d_ball < STOP_VACATE_TRIGGER_M:
                target = _away_from_ball_point(
                    context, ball, p.pose, STOP_VACATE_TARGET_M
                )
                if (
                    elapsed <= STOP_VACATE_WINDOW_S
                    and dist(p.pose.x, p.pose.y, target[0], target[1]) >= 0.9
                ):
                    p.action = "stopped:vacate"
                    p.omni_move_toward(target, speed=STOP_VACATE_SPEED)
                else:
                    # v2.14:窗口(0.5s@1.0m/s)快撤后改 0.12m/s 径向慢爬,继续远离球。
                    # v2.13 硬停后线上 d1ebca78(第 9 场)仍吃 defender_set_play_
                    # interference + illegalPosition(距球 1.005m<1.45,R-07)各 1 张;
                    # 慢速径向远离满足 R-07 豁免,0.12m/s 在 M-02 2s 观察窗内仅 0.24m。
                    # v2.16:目标被 clamp 到距 pose<0.9m 时(贴边/角旗)直接停,
                    # 不为了 0.3m 的撤离在判定窗里多走;否则 0.10m/s 径向慢爬
                    # (R-07「径向远离」豁免要求 ≥0.05m/s)。
                    if dist(p.pose.x, p.pose.y, target[0], target[1]) < 0.9:
                        p.action = "stopped:hold"
                        p.stop()
                    else:
                        # v2.16(analyst m02284「低」):检测后 0.35s 内先按
                        # 0.3m/s 径向冲出(0.105m<0.3m 安全),再降到 0.10m/s
                        # 慢爬;覆盖 latency comp 偏大、检测时距球 1.3–1.5m 的
                        # R-07 风险窗口。
                        burst = elapsed_detect <= STOP_EARLY_BURST_S
                        speed = (
                            STOP_EARLY_BURST_SPEED if burst else STOP_CRAWL_SPEED
                        )
                        p.action = "stopped:crawl"
                        p.omni_move_toward(target, speed=speed)
                continue
        p.action = "stopped"
        p.stop()


def _act_ready(context: Context, players: list[Player], store) -> None:
    """READY:站到 ready 槽位,到位后立刻站住(进入 SET 需全员静止 5s)。

    槽位分配**进入 READY 时锁定一次**存进 store.ready_assignment:
    如果每帧都按"离槽最近"重新贪心,机器人在移动过程中会互相交换槽位、
    来回走不停 → READY 永远凑不够 5s 静止 → 45s 超时强制进 SET,
    随后在 SET 里位置非法吃罚(iteration-08 实测:robot1 离中心 1.55m、
    robot3 在对方半场各吃 30s)。

    站位合法性:非开球方必须在本方半场且离中心 >1.55m(留 0.3m 余量);
    开球方可以在中圈内。
    """
    game = context.game
    our_kickoff = game is not None and game.kicking_team == context.team_id
    field = context.field
    if our_kickoff:
        slots = [
            (-field.circle_radius, 0.0),                                # 开球主罚预备位(开球方可在圈内)
            (-field.length / 2.0 + field.goal_area_length, 0.0),        # 门将
            (-0.5, field.circle_radius + 2.0),                          # 后场支援
        ]
    else:
        slots = [
            (-field.circle_radius - 0.8, 0.0),                          # 离中心 2.3m(>1.55+余量)
            (-field.length / 2.0 + field.goal_area_length, 0.0),
            (-field.length / 2.0 + field.penalty_area_length, 0.0),
        ]

    assignment = getattr(store, "ready_assignment", None)
    active_ids = {p.id for p in players}
    if not isinstance(assignment, dict):
        assignment = None
    need_rebuild = assignment is None or (
        context.game is not None
        and getattr(store, "prev_phase", None) != Phase.READY
    )
    if need_rebuild:
        assignment = {}
        remaining = list(players)
        for slot in slots:
            if not remaining:
                break
            p = min(remaining, key=lambda q: dist(q.pose.x, q.pose.y, slot[0], slot[1]))
            assignment[p.id] = slot
            remaining.remove(p)
        store.ready_assignment = assignment
    else:
        # 新上场/解罚的球员:补到空闲槽位(已分配的槽位不换人)。
        used = {tuple(v) for k, v in assignment.items() if k in active_ids}
        free = [s for s in slots if tuple(s) not in used]
        for p in players:
            if p.id not in assignment and free:
                slot = min(free, key=lambda s: dist(p.pose.x, p.pose.y, s[0], s[1]))
                assignment[p.id] = slot
                free.remove(slot)

    for p in players:
        slot = assignment.get(p.id)
        if slot is None:
            continue
        p.action = "ready"
        p.walk_to(slot, face=0.0, avoid_ball=True, avoid_robots=True)



# ======================================================================
# 战场可视化 —— 显示球位置 + 球员到球的距离,画到 ROS 可视化
# ======================================================================

def _draw_teammate_marker(p: Player) -> None:
    """我方队员可视化:红色。踢球中→方块,否则→球体。

    每帧对所有球员统一调用(不受 phase/判罚/就绪影响)。标签两行:
    - 上:编号 + 当前高层动作(``p.action``),踢球中追加 ``[KICK]``。
    - 通过形状(方块 vs 球体)再次区分是否进入 kick 状态。
    """
    from .framework import debugdraw

    if p.pose is None:
        return
    red = (1.0, 0.2, 0.2)
    if p.is_kicking:
        debugdraw.cube(p.pose.x, p.pose.y, rgb=red, scale=0.38, ns="teammate")
    else:
        debugdraw.point(p.pose.x, p.pose.y, rgb=red, scale=0.3, ns="teammate")
    kick_tag = " [KICK]" if p.is_kicking else ""
    label = f"{p.id}:{p.action}{kick_tag}"
    debugdraw.text(p.pose.x, p.pose.y, label, rgb=(1.0, 0.9, 0.6), ns="teammate_id")


def _analyze_and_draw(context: Context, players: list[Player], store) -> None:
    """每帧:计算球员到球的距离,画可视化。

    不再依赖 analysis 模块;距离改为基于球当前位置。
    """
    from .framework import debugdraw

    ball = context.ball

    # 球不可见:无可视化
    if ball is None:
        return

    # 1. 画球当前位置(绿色点)
    debugdraw.point(ball.x, ball.y, rgb=(0.0, 1.0, 0.0), scale=0.2, ns="ball_current")

    # 2. 球员到球的距离:我方(红标签)+ 敌方(蓝标签)
    for p in players:
        if p.pose is None:
            continue
        d = dist(p.pose.x, p.pose.y, ball.x, ball.y)
        debugdraw.text(
            p.pose.x + 0.3, p.pose.y - 0.3, f"{d:.1f}m",
            rgb=(1.0, 0.6, 0.6), ns="dist_ours",
        )
    for r in context.opponents.values():
        if r.pose is None:
            continue
        d = dist(r.pose.x, r.pose.y, ball.x, ball.y)
        debugdraw.text(
            r.pose.x + 0.3, r.pose.y - 0.3, f"{d:.1f}m",
            rgb=(0.6, 0.6, 1.0), ns="dist_opp",
        )

