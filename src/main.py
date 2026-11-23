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
from .utils import angle_to, clamp, dist, opponent_goal, own_goal


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

    @staticmethod
    def play(context: Context, players: list[Player], store) -> None:
        phase = get_phase(context)
        store.prev_phase = store.cur_phase
        store.cur_phase = phase

        # 画可视化(每帧)
        _analyze_and_draw(context, players, store)

        # 当前 phase 以 label 画在场外。
        from .framework import debugdraw
        g = context.game
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
            _act_opp_kickoff(context, active)
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
        # 界外球/球门球/间接任意球:需二次触球才能进球。第一脚短传给最近的
        # 队友,由队友完成第二次触球后再进攻;没有队友可传时退化为向前推。
        mate = None
        best = math.inf
        for mate_id, mate_state in context.teammates.items():
            if mate_id == taker_id or mate_state.pose is None:
                continue
            if active_ids is not None and mate_id not in active_ids:
                continue
            d = dist(ball.x, ball.y, mate_state.pose.x, mate_state.pose.y)
            if d < best:
                best = d
                mate = mate_state
        if mate is not None and best > 0.8:
            # v2.3:短传落点里收、避边线至少 1.2m,并把 y 向中路拉,降低
            # 「界外球/球门球第一脚把球踢出界 → set_play_retake」的概率。
            half_w = context.field.width / 2.0
            tx = clamp(mate.pose.x, -half_length + 1.2, half_length - 1.2)
            ty = mate.pose.y
            if abs(ty) > half_w - 1.5:
                ty = 0.6 * ty
            # v2.6:落点必须比球更靠前(球门方向),且不能深到己方半场深处。
            tx = max(tx, ball.x + 1.0, -1.0)
            tx = clamp(tx, -half_length + SET_PLAY_TARGET_MARGIN_M,
                       half_length - SET_PLAY_TARGET_MARGIN_M)
            ty = clamp(ty, -half_w + 1.2, half_w - 1.2)
            target = (tx, ty)
            pass_dist = dist(ball.x, ball.y, tx, ty)
            power = clamp(
                SET_PLAY_PASS_POWER_BASE + SET_PLAY_PASS_POWER_PER_M * pass_dist,
                SET_PLAY_PASS_POWER_MIN,
                SET_PLAY_PASS_POWER_MAX,
            )
        else:
            target = (
                min(ball.x + SET_PLAY_FORWARD_M, half_length - SET_PLAY_TARGET_MARGIN_M),
                clamp(ball.y * 0.4, -2.4, 2.4),
            )
            power = KICK_POWER_SET_PLAY_FORWARD
    return angle_to(ball.x, ball.y, target[0], target[1]), power


def _act_normal(context: Context, players: list[Player], store) -> None:
    """NORMAL:距球最近者 attack,剩下人里离己方门最近者 guard,其余 support。

    ``players`` 是本帧可行动球员(已就绪、pose 已知),这里直接挑角色并执行。
    """
    if not players:
        return

    # 球不可见(约 1.5s 没更新):不要乱走,原地停住等待球重新出现。
    if context.ball is None:
        for p in players:
            p.action = "no_ball"
            p.stop()
        return

    # v2.0 协同分工:先固定 1 台门将(离己方门最近),绝不让门将参与抢球;
    # 剩下两人里离球最近者当 primary(抢/带/射),最后一人当 support(接应/保护)。
    # 旧实现「离球最近者 attack,其余里离己方门最近者 guard」在结构上允许门将
    # 被选为 attacker 而离门出击(线上 replay 已看到门前无人),这里先锁门将。
    gx, gy = own_goal(context)
    keeper = min(players, key=lambda p: dist(p.pose.x, p.pose.y, gx, gy))
    # v2.5:门将粘滞。线上 v2.4(0:5)复盘发现门将角色在两台深位机器人之间反复
    # 切换,两人都往门前挤/互相推挤,导致门线出现空档。这里保留上一帧门将,除非
    # 它已明显离门更远(>1.5m)。
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
    if field_players:
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

    for p in rest:
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
    for idx, p in enumerate(rest):
        target = _field_point(
            context, -1.0, 2.4 if idx % 2 == 0 else -2.4, 0.3,
        )
        needs_reposition = p.pose is not None and (
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


def _act_opp_kickoff(context: Context, players: list[Player]) -> None:
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
        for p in players:
            p.action = "setplay:placement"
            p.stop()
        return

    if not players:
        return
    ball = context.ball
    if ball is None:
        for p in players:
            p.action = "setplay:no_ball"
            p.stop()
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
            0.25,
        )
        taker.walk_to(approach, face=kick_dir, avoid_ball=True)
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
        for p in players:
            p.action = "setplay:placement"
            p.stop()
        return
    ball = context.ball
    if ball is None:
        for p in players:
            p.action = "opp_setplay:no_ball"
            p.stop()
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
        if d_ball < SET_PLAY_DEF_GAP_M:
            # 仍在 1.45m 判定区附近:用全向平移(不转身)快速撤离。walk_to 在远距离
            # 会先原地转身(MAX_ANGULAR=2rad/s,转 180° 约 1.6s),来不及躲开主罚触球。
            p.action = "opp_setplay:escape"
            p.omni_move_toward(target)
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
    0.35s、速度 1.0m/s;③只撤离「距球 <1.8m 的我方非门将」;④窗口结束后对
    所有球员(含撤离名单)显式 p.stop(),目标摆球期 0 罚单。
    我方定位球摆球时不移动;SET 阶段一律静止。
    """
    g = context.game
    if g is None:
        for p in players:
            p.action = "stopped"
            p.stop()
        return

    if store.prev_phase != Phase.STOPPED:
        # v2.6:-0.35s 补偿裁判状态的发布延迟,让宽限窗口对齐真实计时点。
        store.stopped_since = context.now - STOP_STATE_LATENCY_COMP_S
    elapsed = context.now - getattr(store, "stopped_since", context.now)

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
            if d_ball < RESTART_AVOID_RADIUS_M + 0.35 and elapsed <= STOP_VACATE_WINDOW_S:
                target = _away_from_ball_point(
                    context, ball, p.pose, RESTART_AVOID_RADIUS_M + 0.55
                )
                p.action = "stopped:vacate"
                p.omni_move_toward(target, speed=STOP_VACATE_SPEED)
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

