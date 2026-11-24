"""Player:单个机器人的控制 handle —— 用户可直接编辑这个类。

平台原语(set_velocity / kick / release_kick / request_mode / get_up)委托给注入的
``_backend``(framework 层);状态 property(pose / mode / is_fallen / penalty)从
``self.context`` 或 backend 读。

走位行为(walk_to / face_to / ensure_ready)也是 Player 方法:它们本质是"对本
球员下命令的动词",且未来加迟滞/避障需要的跨帧状态可直接挂 ``self``。纯坐标计算
(dist / angle_to / 球门坐标等)才放 utils/geom。

实例跨整场比赛存活;``self.context`` 每帧被框架覆写。用户想加自己的拐棍方法直接
在这里加。
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

from .framework.types import Context, Penalty, Pose2D, SetPlay
from .framework import debugdraw

from .param import *
from .utils.geom import (
    angle_to,
    clamp,
    dist,
    normalize_angle,
    opponent_goal,
    own_goal,
    own_goal_area_center,
)
from .utils.obstacles import collect_obstacles
from .utils.path_planner import plan_global_path

if TYPE_CHECKING:
    from .framework.config import SoccerConfig


__all__ = ["Player"]


_log = logging.getLogger(__name__)

def _heading_clearance(
    px: float, py: float, heading: float, obstacles: list,
) -> float:
    """用于局部避障。沿 (px,py) 朝 ``heading`` 的 lookahead 射线,到最近障碍的余量(dist - radius)。

    只考虑**前方**(投影 t>0)的障碍;身后 / 侧后的障碍不挡这个方向,跳过——否则贴近
    任何障碍(哪怕正后方)都会把所有方向的余量拉低,误判"全堵"。
    无障碍返回 inf;越大越空,负值表示会撞。
    """
    ux, uy = math.cos(heading), math.sin(heading)
    min_clear = math.inf
    for obs in obstacles:
        t = (obs.x - px) * ux + (obs.y - py) * uy
        if t <= 0.0:
            continue                      # 障碍在身后/侧后,不挡此方向
        if t > PLAN_LOOKAHEAD:
            t = PLAN_LOOKAHEAD
        nx, ny = px + ux * t, py + uy * t
        clear = math.hypot(obs.x - nx, obs.y - ny) - obs.radius
        if clear < min_clear:
            min_clear = clear
    return min_clear


def _behind_ball(
    ball_x: float, ball_y: float, aim: tuple[float, float], offset: float,
) -> tuple[float, float]:
    """用于计算站位。球在 球→``aim`` 连线上的"后方"点:从球沿【背离 aim】方向退 ``offset`` 米。

    追球走位目标用它:球落在机器人与 ``aim`` 之间,到位时天然对准 aim 方向。
    aim 与球重合(退化)时,方向不定,直接返回球位。
    """
    dx, dy = aim[0] - ball_x, aim[1] - ball_y
    d = math.hypot(dx, dy)
    if d < 1e-6:
        return (ball_x, ball_y)
    ux, uy = dx / d, dy / d              # 球指向 aim 的单位向量
    return (ball_x - ux * offset, ball_y - uy * offset)   # 背离 aim 退 offset


class Player:
    """单个球员的 handle。可以在这里加入新的技术动作。
    """

    def __init__(
        self,
        player_id: int,
        config: "SoccerConfig",
        _backend: object | None,
    ) -> None:
        self.id: int = player_id
        self.config: "SoccerConfig" = config
        self._backend = _backend           # 机器人控制接口的包装，通常不用改
        self.context: Context | None = None

        # 当前高层动作名(仅供可视化/调试)。策略分派层每帧写入;有子状态的动作
        # (如 guard)在方法内部细化。可视化 pass 读它标注文字,见 main.py。
        self.action: str = "init"

        # SDK 缓存字段,框架后台会自动更新
        self._mode: str | None = None
        self._fall_down_state: str | None = None

        # 避障绕行侧记忆(跨帧;None=当前无绕行)
        self._avoid_side: float | None = None

        # 踢球迟滞状态(跨帧)
        self._kicking: bool = False

        # block/guard 的跨帧迟滞状态
        self._block_pressing: bool = False
        self._guard_threatened: bool = False
        # 门线撞球进门迟滞状态
        self._goal_line_push: bool = False
        # support 卡住后临时转 attack 的跨帧状态
        self._support_last_pos: tuple[float, float] | None = None
        self._support_stationary_since: float | None = None
        self._support_last_update_at: float | None = None

    # ------------------------------------------------------------------
    # 状态读取
    # ------------------------------------------------------------------

    @property
    def is_kicking(self) -> bool:
        """当前是否处于踢球状态。"""
        return self._kicking

    @property
    def pose(self) -> Pose2D | None:
        ctx = self.context
        if ctx is None:
            return None
        robot = ctx.teammates.get(self.id)
        return None if robot is None else robot.pose

    @property
    def mode(self) -> str | None:
        if self._backend is not None:
            return self._backend.mode
        return self._mode

    @property
    def is_fallen(self) -> bool:
        return self.fall_down_state not in (None, "normal")

    @property
    def fall_down_state(self) -> str | None:
        if self._backend is not None:
            return getattr(self._backend, "fall_down_state", None)
        return self._fall_down_state

    @property
    def penalty(self) -> Penalty:
        ctx = self.context
        if ctx is None or ctx.game is None:
            return Penalty.NONE
        state = ctx.game.get_player_state(self.config.team_id, self.id)
        return Penalty.NONE if state is None else state.penalty

    @property
    def is_penalized(self) -> bool:
        return self.penalty != Penalty.NONE

    # ------------------------------------------------------------------
    # 底盘控制
    # ------------------------------------------------------------------

    def set_velocity(self, vx: float, vy: float, vyaw: float) -> None:
        if self._backend is None:
            _log.debug(
                "player %d set_velocity vx=%.3f vy=%.3f vyaw=%.3f (no backend)",
                self.id, vx, vy, vyaw,
            )
            return
        self._backend.set_velocity(vx, vy, vyaw)

    def stop(self) -> None:
        self.release_kick()
        self.set_velocity(0.0, 0.0, 0.0)

    # ------------------------------------------------------------------
    # 踢球
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # v3.0 patch1(#22): 贴线球踢球方向可行域夹取
    # ------------------------------------------------------------------
    def _axis_bounds(self, ball_c: float, off: float, lim: float) -> tuple[float, float] | None:
        """后侧点约束 |ball_c - off*u| <= lim 给出的 u 可行区间(off>0)。"""
        if abs(off) < 1e-9:
            return None
        lo = (ball_c - lim) / off
        hi = (ball_c + lim) / off
        if lo > hi:
            lo, hi = hi, lo
        if lo > hi:
            return None
        return lo, hi

    def _safe_kick_direction(self, direction: float) -> float:
        """v3.0 patch1(#22): 后侧点出界时把方向分量夹进可行域;失败回退旧旋转搜索。"""
        ctx = self.context
        ball = ctx.ball if ctx is not None else None
        if ball is None or self.pose is None:
            return direction
        half_l = ctx.field.length / 2.0
        half_w = ctx.field.width / 2.0
        lim_x = half_l - KICK_BEHIND_MARGIN_M
        lim_y = half_w - KICK_BEHIND_MARGIN_M
        off = KICK_BEHIND_OFFSET_M

        def behind_inside(d: float) -> bool:
            bx = ball.x - math.cos(d) * off
            by = ball.y - math.sin(d) * off
            return abs(bx) <= lim_x and abs(by) <= lim_y

        if behind_inside(direction):
            return direction

        ux, uy = math.cos(direction), math.sin(direction)
        bx = self._axis_bounds(ball.x, off, lim_x)
        by = self._axis_bounds(ball.y, off, lim_y)
        if bx is not None and by is not None:
            cx = clamp(ux, bx[0], bx[1])
            cy = clamp(uy, by[0], by[1])
            n = math.hypot(cx, cy)
            if n > 1e-6:
                cand = math.atan2(cy / n, cx / n)
                if behind_inside(cand) and not (ball.x < 0.0 and math.cos(cand) < -0.2):
                    return cand
        # 回退:旧 ±0.35rad 旋转搜索(保留己方半场不朝己门的保护)。
        for k in range(1, 9):
            for sign in (1.0, -1.0):
                cand = normalize_angle(direction + sign * 0.35 * k)
                if behind_inside(cand) and not (ball.x < 0.0 and math.cos(cand) < -0.2):
                    return cand
        return direction

    def kick(
        self,
        kick_direction: float | None = None,
        power: float = KICK_POWER_DEFAULT,
    ) -> None:
        pose = self.pose
        if pose is None:
            _log.warning("player %d kick skipped: pose unknown", self.id)
            return

        ball = self.context.ball if self.context is not None else None
        if ball is None:
            _log.warning("player %d kick skipped: ball unknown", self.id)
            return

        if kick_direction is None:
            kick_plan = self.plan_kick()
            if kick_plan is None:
                _log.warning("player %d kick skipped: kick plan unavailable", self.id)
                return
            kick_direction, power = kick_plan

        if self._backend is None:
            _log.debug(
                "player %d kick ball=(%.3f, %.3f) dir=%.3f (no backend)",
                self.id, ball.x, ball.y, kick_direction,
            )
            return
        # 场地坐标 → 体坐标(用当前 pose)
        dx = ball.x - pose.x
        dy = ball.y - pose.y
        cos_t = math.cos(pose.theta)
        sin_t = math.sin(pose.theta)
        ball_x_body = dx * cos_t + dy * sin_t
        ball_y_body = -dx * sin_t + dy * cos_t
        # v3.0 patch1(#22): 后侧点出界时改成场内可达的踢球方向。
        kick_direction = self._safe_kick_direction(kick_direction)
        kick_direction = normalize_angle(kick_direction)
        direction_body = normalize_angle(kick_direction - pose.theta)
        power_clamped = max(KICK_POWER_MIN, min(KICK_POWER_MAX, power))
        self._kicking = True
        self._backend.kick(direction_body, power_clamped, ball_x_body, ball_y_body)

    def _coordinated_kick_plan(self) -> tuple[float, float] | None:
        """协同进攻踢球决策(v2.0):近门射门 / 推进带球 / 被逼抢解围。

        线上 replay 分析(11-22 1:2、0:9、0:3 三场)发现:旧逻辑只要进入踢球
        距离就朝对方球门开大脚,力度随距离增大,球权在几秒内就丢回给对方,
        既形不成射门也把阵型拉开。这里按距离分三种处理:
        - 距球门 <= SHOOT_RANGE_M:瞄准远离对方门将的一侧门内射门;
        - 更远:向对方球门方向短推 PROGRESS_AHEAD_M(避让最近对手),保持球权;
        - 己方半场且被对手贴身:朝对方半场边线大力解围。
        """
        ctx = self.context
        ball = ctx.ball if ctx is not None else None
        if ctx is None or ball is None:
            return None

        half_l = ctx.field.length / 2.0
        half_w = ctx.field.width / 2.0
        goal_x, goal_y = opponent_goal(ctx)
        dist_goal = math.hypot(goal_x - ball.x, goal_y - ball.y)

        opp_poses: list[Pose2D] = []
        for opp in (ctx.opponents or {}).values():
            if opp.pose is not None:
                opp_poses.append(opp.pose)
        nearest_opp: Pose2D | None = None
        nearest_opp_dist = math.inf
        for op in opp_poses:
            dd = math.hypot(op.x - ball.x, op.y - ball.y)
            if dd < nearest_opp_dist:
                nearest_opp_dist, nearest_opp = dd, op

        # v2.12(P0-a): 己方三区一律直接解围,优先于绕位/推进。第 7 场两个失球
        # 都是己方三区静止球(144.4-146.5/549.9-552.5),我方最近者绕位 1.5s
        # 不触球、被对手 0.35m 先捅。方向朝对方半场边线(避免中路送二点)。
        if ball.x < OWN_THIRD_CLEAR_BALL_X:
            side = 1.0 if ball.y >= 0.0 else -1.0
            self.action = "attack:own_third_clear"
            return angle_to(ball.x, ball.y, 0.0, side * (half_w - 1.2)), KICK_POWER_CLEAR

        # 己方半场被贴身逼抢:向前解围,别在门前横传。v2.12(P1): 落点改朝边线,
        # 避免解围从对方底线出界白送门球(第 7 场 2 次)或中路送二点。
        if ball.x < -1.0 and nearest_opp_dist < 1.4:
            side = 1.0 if ball.y >= 0.0 else -1.0
            clear_x = half_l - KICK_CLEAR_TARGET_X_FROM_GOAL
            clear_y = side * (half_w - KICK_CLEAR_LATERAL_MARGIN_M)
            self.action = "attack:clear"
            return angle_to(ball.x, ball.y, clear_x, clear_y), KICK_POWER_CLEAR

        # 近门:射门。瞄向远离对方门将的一侧门内。
        if dist_goal <= SHOOT_RANGE_M:
            their_keeper: Pose2D | None = None
            keeper_dist = math.inf
            for op in opp_poses:
                kd = math.hypot(op.x - goal_x, op.y - goal_y)
                if kd < keeper_dist:
                    keeper_dist, their_keeper = kd, op
            # 门柱内侧:门半宽 1.3,瞄 ±(1.3-0.35)=±0.95,朝远离对方门将的一侧。
            aim_abs = max(0.5, ctx.field.goal_width / 2.0 - SHOOT_TARGET_INSET_M)
            if their_keeper is not None and their_keeper.y > 0.0:
                aim_y = -aim_abs
            elif their_keeper is not None and their_keeper.y < 0.0:
                aim_y = aim_abs
            else:
                aim_y = aim_abs if ball.y <= 0.0 else -aim_abs
            aim_x = goal_x - 0.15
            power = clamp(
                KICK_POWER_SHOOT_BASE
                + KICK_POWER_PER_M * (SHOOT_RANGE_M - dist_goal),
                KICK_POWER_SHOOT_BASE,
                SHOOT_POWER_MAX,
            )
            self.action = "attack:shoot"
            return angle_to(ball.x, ball.y, aim_x, aim_y), power

        # 远距离:短推推进。目标点 = 球向对方门方向 PROGRESS_AHEAD_M,
        # 若最近对手压在该方向上,则沿垂直方向让开再推进。
        dx, dy = goal_x - ball.x, goal_y - ball.y
        norm = math.hypot(dx, dy)
        if norm < 1e-6:
            return None
        ux, uy = dx / norm, dy / norm
        px = ball.x + ux * PROGRESS_AHEAD_M
        py = ball.y + uy * PROGRESS_AHEAD_M
        if nearest_opp is not None:
            # 若推进路线上对手太近,把目标点沿垂直方向偏一点。
            if math.hypot(nearest_opp.x - px, nearest_opp.y - py) < 0.9:
                for sign in (1.0, -1.0):
                    cx = px - uy * sign * 1.4
                    cy = py + ux * sign * 1.4
                    if (math.hypot(nearest_opp.x - cx, nearest_opp.y - cy)
                            > math.hypot(nearest_opp.x - px, nearest_opp.y - py)):
                        px, py = cx, cy
                        break
        px = clamp(px, -half_l + 0.8, half_l - 0.8)
        py = clamp(py, -half_w + 0.8, half_w - 0.8)
        self.action = "attack:progress"
        return angle_to(ball.x, ball.y, px, py), KICK_POWER_DRIBBLE

    def plan_kick(self) -> tuple[float, float] | None:
        """计算踢球方向和力度。

        从当前球位踢向对方球门中心;力度随距门距离线性增长(门前轻推、远射加力),
        后场解围仍用 ``KICK_POWER_BACKFIELD``。
        返回 ``(kick_direction, kick_power)``;球或上下文不可用时返回 None。
        """
        ctx = self.context
        ball = ctx.ball if ctx is not None else None
        if ctx is None or ball is None:
            return None

        kick_target = opponent_goal(ctx)
        kick_direction = angle_to(ball.x, ball.y, *kick_target)
        distance_to_goal = math.hypot(kick_target[0] - ball.x, kick_target[1] - ball.y)
        if self._in_backfield():
            kick_power = KICK_POWER_BACKFIELD
        else:
            kick_power = clamp(
                KICK_POWER_BASE + KICK_POWER_PER_M * distance_to_goal,
                KICK_POWER_BASE,
                KICK_POWER_CAP,
            )
        kick_target = self._goal_target_for_direction(kick_direction)

        self._draw_kick_target(kick_target)
        return kick_direction, kick_power

    def _goal_target_for_direction(
        self, kick_direction: float,
    ) -> tuple[float, float]:
        """把射门方向投到对方门线上,用于可视化踢球目标。"""
        ctx = self.context
        ball = ctx.ball if ctx is not None else None
        if ctx is None or ball is None:
            return (0.0, 0.0)

        dx = math.cos(kick_direction)
        if dx <= 1e-6:
            return opponent_goal(ctx)
        goal_x = ctx.field.length / 2.0
        t = max(0.0, (goal_x - ball.x) / dx)
        return (goal_x, ball.y + math.sin(kick_direction) * t)

    def _in_backfield(self) -> bool:
        """球在我方后场时,默认踢球加大力度。"""
        ctx = self.context
        ball = ctx.ball if ctx is not None else None
        if ctx is None or ball is None:
            return False
        # own_penalty_edge_x = -ctx.field.length / 2.0 + ctx.field.penalty_area_length
        # return ball.x < own_penalty_edge_x
        return ball.x < 0

    def _draw_kick_target(self, target: tuple[float, float]) -> None:
        """以 X 标出 plan_kick 选择的踢球目标。"""
        from .framework import debugdraw

        x, y = target
        s = KICK_TARGET_MARK_SIZE_M
        debugdraw.line(
            [(x - s, y - s), (x + s, y + s)],
            rgb=(1.0, 0.0, 1.0), ns="kick_target",
        )
        debugdraw.line(
            [(x - s, y + s), (x + s, y - s)],
            rgb=(1.0, 0.0, 1.0), ns="kick_target",
        )

    def release_kick(self) -> None:
        self._kicking = False  # 清除踢球迟滞标志(取消方块显示)
        if self._backend is None:
            _log.debug("player %d release_kick (no backend)", self.id)
            return
        self._backend.release_kick()

    def kick_can_score(self, kick_direction: float) -> bool:
        """判断从当前球位按 ``kick_direction`` 踢,直线轨迹是否能进对方球门。
        """
        ctx = self.context
        ball = ctx.ball if ctx is not None else None
        if ctx is None or ball is None:
            return False

        goal_x = ctx.field.length / 2.0
        dx = math.cos(kick_direction)
        dy = math.sin(kick_direction)
        if dx <= 1e-6:
            return False

        half_goal = ctx.field.goal_width / 2.0
        if half_goal <= 0.0:
            return False
        if ball.x >= goal_x:
            y_at_goal = ball.y
        else:
            t = (goal_x - ball.x) / dx
            if t < 0.0:
                return False
            y_at_goal = ball.y + dy * t
        return -half_goal <= y_at_goal <= half_goal

    # ------------------------------------------------------------------
    # 慢操作（同步接口异步调取，使得不阻塞）
    # ------------------------------------------------------------------

    @property
    def is_getting_up(self) -> bool:
        """起身是否已排队或仍在 SDK 中执行。"""
        return self._backend is not None and self._backend.is_getting_up

    def request_mode(self, mode: str) -> None:
        if self._backend is None:
            _log.debug("player %d request_mode -> %s (no backend)", self.id, mode)
            return
        self._backend.request_mode(mode)

    def get_up(self) -> None:
        if self._backend is None:
            _log.debug("player %d get_up (no backend)", self.id)
            return
        self._backend.get_up()

    # ------------------------------------------------------------------
    # 走位
    # ------------------------------------------------------------------

    def ensure_ready(self) -> bool:
        """活性自理:摔倒→起身,非 walk→切模式(都异步、不产生移动)。

        返回本帧是否可执行动作(True=已就绪)。起身任务未返回终态前不能切模式,
        否则 set_mode 会打断/顶掉起身。
        """
        if self.is_getting_up:
            return False
        if self.is_fallen:
            self.get_up()
            return False
        if self.mode != "walk":
            self.request_mode("walk")
            return False
        return True

    def face_to(self, target_theta: float) -> None:
        """原地转向到目标朝向。"""
        if self.pose is None:
            self.stop()
            return
        err = normalize_angle(target_theta - self.pose.theta)
        self.set_velocity(0.0, 0.0, self._angular(err))

    def walk_to(
        self,
        target: tuple[float, float],
        *,
        face: float | None = None,
        avoid_ball: bool = False,
        avoid_robots: bool = False,
        arrive_dist: float = ARRIVE_DIST,
    ) -> bool:
        """走向目标点。返回是否已到达。

        避障(局部规划器,简化版 VFH):``avoid_ball`` / ``avoid_robots`` 开启时,把
        球 / 机器人 / 球门结构收集成圆形障碍,在机器人周围扫一圈候选方向,选"最朝
        目标 + 前方 ``PLAN_LOOKAHEAD`` 内不撞障碍"的方向前进。能处理多障碍、凹形
        结构和对称冲突,比单障碍绕行 / 势场排斥稳。

        行走两种模式:近距离全向,远距离转身-走。``face`` 指定到达/近距离时的朝向。
        """
        self.release_kick() # 踢球状态下，走位会被覆盖，先取消踢球状态
        pose = self.pose
        if pose is None:
            self.stop()
            return False

        tx, ty = target
        dx = tx - pose.x
        dy = ty - pose.y
        distance = math.hypot(dx, dy)

        if distance < arrive_dist:
            # 已到达:按需转到目标朝向
            if face is not None:
                err = normalize_angle(face - pose.theta)
                if abs(err) > 0.1:
                    self.set_velocity(0.0, 0.0, self._angular(err))
                else:
                    self.stop()
            else:
                self.stop()
            return True

        # 规划:默认全局 A*,找不到路时退回旧局部规划。
        goal_dir = math.atan2(dy, dx)
        planned_path: list[tuple[float, float]] | None = None
        waypoint: tuple[float, float] | None = None
        if (avoid_ball or avoid_robots) and self.context is not None:
            obstacles = collect_obstacles(
                self.context, self.id,
                ball=avoid_ball, robots=avoid_robots,
                goals=(avoid_ball or avoid_robots),
            )
            if USE_GLOBAL_PATH_PLANNER:
                planned_path = plan_global_path(
                    self.context,
                    (pose.x, pose.y),
                    (tx, ty),
                    obstacles,
                )
                if planned_path is not None:
                    waypoint = self._path_waypoint(pose, planned_path)
                    heading = angle_to(pose.x, pose.y, waypoint[0], waypoint[1])
                else:
                    heading = self._plan_heading(pose, goal_dir, obstacles)
            else:
                heading = self._plan_heading(pose, goal_dir, obstacles)
        else:
            heading = goal_dir

        # 可视化:目标点(绿)、到目标连线(灰)、规划朝向(黄箭头)、
        # 前方探测射线(青,长度=lookahead;规划器"看"的范围,无 path/途径点概念)
        from .framework import debugdraw
        debugdraw.point(tx, ty, rgb=(0.0, 1.0, 0.0), scale=0.15, ns="target")
        debugdraw.line([(pose.x, pose.y), (tx, ty)], rgb=(0.4, 0.4, 0.4), ns="to_target")
        if planned_path is not None and len(planned_path) >= 2:
            debugdraw.line(planned_path, rgb=(0.2, 0.8, 1.0), ns="global_path")
        if waypoint is not None:
            debugdraw.point(
                waypoint[0], waypoint[1],
                rgb=(0.2, 0.8, 1.0), scale=0.12, ns="global_waypoint",
            )
        debugdraw.arrow(
            pose.x, pose.y,
            pose.x + math.cos(heading) * 0.6, pose.y + math.sin(heading) * 0.6,
            rgb=(1.0, 1.0, 0.0), ns="heading",
        )
        debugdraw.line(
            [(pose.x, pose.y),
             (pose.x + math.cos(heading) * PLAN_LOOKAHEAD,
              pose.y + math.sin(heading) * PLAN_LOOKAHEAD)],
            rgb=(0.0, 0.8, 0.8), ns="lookahead",
        )

        if distance <= OMNI_DIST:
            # 近距离:全向行走,沿 heading 平移,同时转向 face
            wdx, wdy = math.cos(heading) * distance, math.sin(heading) * distance
            cos_t, sin_t = math.cos(pose.theta), math.sin(pose.theta)
            vx = LINEAR_GAIN * (wdx * cos_t + wdy * sin_t)
            vy = LINEAR_GAIN * (-wdx * sin_t + wdy * cos_t)
            speed = math.hypot(vx, vy)
            if speed > MAX_LINEAR:
                vx *= MAX_LINEAR / speed
                vy *= MAX_LINEAR / speed
            vyaw = (
                self._angular(normalize_angle(face - pose.theta))
                if face is not None else 0.0
            )
            self.set_velocity(vx, vy, vyaw)
        else:
            # 远距离:转身-走-转身,朝 heading
            angle_err = normalize_angle(heading - pose.theta)
            if abs(angle_err) > TURN_THRESHOLD:
                self.set_velocity(0.0, 0.0, self._angular(angle_err))
            else:
                vx = clamp(
                    LINEAR_GAIN * distance * math.cos(angle_err), 0.0, MAX_LINEAR,
                )
                self.set_velocity(vx, 0.0, self._angular(angle_err))
        return False

    def omni_move_toward(
        self,
        target: tuple[float, float],
        speed: float = OMNI_ESCAPE_SPEED,
    ) -> None:
        """全向平移向目标点靠近：不先转身，直接按体坐标 (vx, vy) 平移。

        用于定位球摆球宽限期/对手主罚前的快速撤离。常规 ``walk_to`` 在远距离会
        先原地转身(MAX_ANGULAR=2 rad/s，转 180° 约 1.6s)，而 1.45m 避让规则只
        看「主罚触球瞬间」的位置，来不及转完就会吃 R-07；这里用 omni 步态省掉转身。
        """
        pose = self.pose
        if pose is None:
            self.stop()
            return
        dx = target[0] - pose.x
        dy = target[1] - pose.y
        distance = math.hypot(dx, dy)
        if distance < ARRIVE_DIST:
            self.stop()
            return
        v = min(speed, LINEAR_GAIN * distance)
        wx = dx / distance * v
        wy = dy / distance * v
        cos_t = math.cos(pose.theta)
        sin_t = math.sin(pose.theta)
        vx = wx * cos_t + wy * sin_t
        vy = -wx * sin_t + wy * cos_t
        self.release_kick()
        self.set_velocity(vx, vy, 0.0)

    def _path_waypoint(
        self, pose: Pose2D, path: list[tuple[float, float]],
    ) -> tuple[float, float]:
        """Pick a short lookahead waypoint from a planned global path."""
        if not path:
            return (pose.x, pose.y)
        prev = (pose.x, pose.y)
        points = path[1:] if len(path) > 1 else path
        for point in points:
            seg_len = dist(prev[0], prev[1], point[0], point[1])
            if seg_len >= GLOBAL_PATH_LOOKAHEAD_M:
                ratio = GLOBAL_PATH_LOOKAHEAD_M / max(seg_len, 1e-6)
                return (
                    prev[0] + (point[0] - prev[0]) * ratio,
                    prev[1] + (point[1] - prev[1]) * ratio,
                )
            prev = point
        return path[-1]

    def _plan_heading(
        self, pose: Pose2D, goal_dir: float, obstacles: list,
    ) -> float:
        """扫候选方向,选最朝目标且前方够空的方向;都不够空时返回最空的那个。

        候选按偏离目标方向 ``|offset|`` 从小到大试;先试哪一侧由 player_id 奇偶决定,
        用来打破两人同侧避让的对称。
        """
        sign_first = 1.0 if self.id % 2 == 0 else -1.0
        best_h = goal_dir
        best_clear = -math.inf

        offsets = [0.0]
        k = 1
        while k * PLAN_STEP <= PLAN_MAX_OFFSET + 1e-9:
            offsets.append(sign_first * k * PLAN_STEP)
            offsets.append(-sign_first * k * PLAN_STEP)
            k += 1

        for off in offsets:
            h = goal_dir + off
            clear = _heading_clearance(pose.x, pose.y, h, obstacles)
            if clear >= PLAN_CLEARANCE:
                return h
            if clear > best_clear:
                best_clear, best_h = clear, h
        return best_h

    # ------------------------------------------------------------------
    # 高层动作(策略在 main.py 里直接调这些)
    # ------------------------------------------------------------------


    def block_path_projection(
        self, opponent_id: int,
    ) -> tuple[float, float, float, float] | None:
        """自己到 对手→球 线段的垂足:返回 (x, y, 垂距, 线段参数 t)。"""
        ctx = self.context
        pose = self.pose
        ball = ctx.ball if ctx is not None else None
        opponent = ctx.opponents.get(opponent_id) if ctx is not None else None
        if ctx is None or pose is None or ball is None or opponent is None:
            return None
        if opponent.pose is None:
            return None

        ax, ay = opponent.pose.x, opponent.pose.y
        bx, by = ball.x, ball.y
        vx, vy = bx - ax, by - ay
        length2 = vx * vx + vy * vy
        if length2 < 1e-6:
            return None

        raw_t = ((pose.x - ax) * vx + (pose.y - ay) * vy) / length2
        t = clamp(raw_t, 0.0, 1.0)
        tx = ax + vx * t
        ty = ay + vy * t
        return tx, ty, dist(pose.x, pose.y, tx, ty), raw_t

    def attack(self, kick_target: tuple[float, float] | None = None) -> None:
        """追球射门。踢向 ``kick_target``(默认对方球门中心)。

        踢球迟滞:距球 ≤ ENTER 进入踢球;进入后距球 > EXIT 才退出(EXIT > ENTER),
        防边界抖动。不避障——正常拼抢要直取球。追球目标设在【球后方】(球→球门连线
        上、背离球门退 ``CHASE_BEHIND_M``),到位时天然对准射门方向。
        """
        ball = self.context.ball if self.context is not None else None
        if ball is None or self.pose is None:
            self.stop()
            return
        if kick_target is None:
            kick_target = opponent_goal(self.context)

        # 球已出界(死球):不要贴着球站。裁判会把球摆回界内,摆球点就在出界点附近
        # (球门球 (6,±2)、角球 (6.95,±4.45)、界外球 (±6.95,±4.45));站得太近会在
        # 主罚触球瞬间被判 defender_touched_before_kick / R-07(iteration-09 实测两次)。
        # 判据用「球心真正越过线」（官方 |y|-(0.11+0.025)>4.5 等），不能提前到
        # width/2-0.15：球贴着边线但仍在场内时若提前撤退，就没人去碰球，
        # 30s 后裁判判 global_game_stuck（iteration-15 开局 32.9s 实测）。
        if (
            abs(ball.y) > self.context.field.width / 2.0 + 0.15
            or abs(ball.x) > self.context.field.length / 2.0 + 0.15
        ):
            self.action = "attack:ball_out"
            half_l = self.context.field.length / 2.0
            half_w = self.context.field.width / 2.0
            # 撤到离出界点更远处(≥2.4m):出界后裁判立刻把摆球点放在原地附近,
            # 我们若只剩 1.5-2m,对方快发界外球时容易在 1.45m 内被判
            # defender_touched_before_kick(headless-07 +14.4s 实测 30s 罚下)。
            tx = ball.x * 0.35
            ty = ball.y * 0.35
            ddx, ddy = tx - ball.x, ty - ball.y
            dd = math.hypot(ddx, ddy)
            if dd < 2.4:
                k = 2.4 / max(dd, 1e-6)
                tx, ty = ball.x + ddx * k, ball.y + ddy * k
            self.walk_to(
                (clamp(tx, -half_l + 1.5, half_l - 1.5),
                 clamp(ty, -half_w + 1.5, half_w - 1.5)),
                face=0.0,
                avoid_ball=False,
                avoid_robots=True,
            )
            return

        half_l = self.context.field.length / 2.0
        half_w = self.context.field.width / 2.0
        # v2.15(P1,Lead):禁止越出对方门线。线上 0116ec1d 机器人追贴线球时被
        # kick 任务的绕球位移带到 x≈7.3 门线外卡死 15s+,而门线前 0.1-0.85m
        # 的散球因此全部补不进;越线即先退回场内再继续进攻。
        if self.pose.x > half_l + 0.02:
            self.release_kick()
            self.action = "attack:recover_inside"
            self.walk_to(
                (half_l - 0.9, clamp(self.pose.y, -half_w + 0.7, half_w - 0.7)),
                face=angle_to(self.pose.x, self.pose.y, ball.x, ball.y),
                avoid_ball=False,
                avoid_robots=True,
            )
            return

        # v3.0 patch2: 禁止越过己方门线(x 上限 -7.12);但球在门口容差带时
        # 属活球必须清理,不回场(否则球卡门线外 15s+ 被捅入)。
        if self.pose.x < -(half_l + 0.02):
            in_goal_mouth_band = (
                abs(ball.x) >= GOAL_MOUTH_BAND_X - 0.12
                and abs(ball.y) <= GOAL_MOUTH_BAND_Y
            )
            if not in_goal_mouth_band:
                self.release_kick()
                self.action = "attack:recover_inside_def"
                self.walk_to(
                    (-(half_l - 0.9), clamp(self.pose.y, -half_w + 0.7, half_w - 0.7)),
                    face=angle_to(self.pose.x, self.pose.y, ball.x, ball.y),
                    avoid_ball=False,
                    avoid_robots=True,
                )
                return

        d = dist(self.pose.x, self.pose.y, ball.x, ball.y)
        self._kicking = d <= (KICK_EXIT_M if self._kicking else KICK_ENTER_M)
        if self._kicking:
            half_l = self.context.field.length / 2.0
            half_w = self.context.field.width / 2.0
            goal_half = self.context.field.goal_width / 2.0
            # v2.15(P1,Lead):球贴近对方门线(≤1.0m)时直接补射入网。
            # v2.16(analyst m02284「中/低」):取消 pose.x>ball.x-0.2 限制——
            # 从场内跑向门线球时旧逻辑仍走 line_clear 把球踢回中圈;现在先绕到
            # 球后 0.45m 再补射。角旗区(|ball.y|>goal_half+0.6)仍走 line_clear,
            # 避免从底线外斜踢变成对方门球。
            if (
                ball.x > half_l - 1.0
                and abs(ball.y) <= goal_half + GOAL_LINE_SHOT_Y_MARGIN_M
            ):
                if self.pose.x <= ball.x - 0.2:
                    self.release_kick()
                    self.action = "attack:goal_line_approach"
                    self.walk_to(
                        (
                            ball.x - 0.45,
                            clamp(ball.y, -half_w + 0.3, half_w - 0.3),
                        ),
                        face=angle_to(self.pose.x, self.pose.y, ball.x, ball.y),
                        avoid_ball=False,
                        avoid_robots=True,
                    )
                    return
                aim_y = clamp(ball.y * 0.5, -(goal_half - 0.2), goal_half - 0.2)
                self.action = "attack:goal_line_shot"
                self.kick(
                    angle_to(ball.x, ball.y, half_l + 0.5, aim_y),
                    SHOOT_POWER_MAX,
                )
                return
            if (
                (abs(ball.x) > half_l - 1.0 or abs(ball.y) > half_w - 1.0)
                and abs(ball.x) < half_l
                and abs(ball.y) < half_w
            ):
                # 贴线活球:朝场中心解围。不要把球往场外踢(v1.10 的"保持距离"
                # 分支反而让球 30s 无人触碰 → global_game_stuck；headless-04/05 实测)。
                # v3.3b(Lead m04025 第 3 条):只处理场内贴线球;球已出界时不追不踢,
                # 交给出界/摆球流程,避免追到场外把球顶出线送 R-06。
                self.action = "attack:line_clear"
                self.kick(angle_to(ball.x, ball.y, 0.0, 0.0), KICK_POWER_LINE_CLEAR)
                return
            coord_plan = self._coordinated_kick_plan()
            if coord_plan is None:
                self.stop()
                return
            kick_direction, kick_power = coord_plan
            # v2.8:回退 v2.7 的对齐门控(kick 反复起停导致进攻瘫痪),恢复直接 kick。
            self.action = "attack:kick"
            self.kick(kick_direction, kick_power)
        else:
            self.release_kick()
            half_l = self.context.field.length / 2.0
            # 只在【对方即将/正在重启】时放弃贴底线的球:追进去会站在对方重启点
            # 旁边,主罚触球瞬间吃 R-07(1.45m 避让),摆球阶段还会因没静止吃 M-02。
            # 但 NORMAL 比赛中的活球必须照常去踢——否则球停在底线附近没人碰,
            # 30s 后裁判判 global_game_stuck 坠球(iteration-04 实测)。
            g = self.context.game
            restart_pending = g is not None and (
                g.stopped
                or (g.set_play is not None and g.set_play is not SetPlay.NONE)
            )
            if restart_pending and ball.x > half_l - 0.35:
                # 退到球后方 2.2m 处等重启:球贴对方底线时,若只退到固定 x 处,
                # 对方 goalKick 摆球点(±6.0)可能在 1.45m 内 → 主罚触球瞬间吃
                # R-07/defender_touched_before_kick(iteration-08 实测)。
                self.action = "attack:hold_line"
                half_w = self.context.field.width / 2.0
                self.walk_to(
                    (clamp(ball.x - 2.2, -half_l + 0.3, half_l - 0.3),
                     clamp(ball.y * 0.3, -half_w + 0.3, half_w - 0.3)),
                    face=0.0,
                    avoid_ball=False,
                    avoid_robots=True,
                )
                return
            behind = _behind_ball(ball.x, ball.y, kick_target, CHASE_BEHIND_M)
            behind = (min(behind[0], half_l - 0.5), behind[1])
            # v3.0 patch2: 己方侧同理,机器人 |x| 不超过 7.12-0.5。
            if behind[0] < -(half_l - 0.5):
                behind = (-(half_l - 0.5), behind[1])
            self.walk_to(behind)

    def guard(self) -> None:
        """守门:封角度站位 + 门前解围。

        线上 v2.1 首战暴露两个问题(0:1):
        1) walk_to(avoid_ball=True) 会把门将从自家门前推开——球滚到门口时门将
           目标点≈球位置,避球力把门将往反方向推,球横穿门线时门将反而后退。
        2) 球贴门线时门将不出击,只站着看球进门。

        v2.2:门将不避球(avoid_ball=False);球进入 KEEPER_CLEAR_RADIUS_M 且在
        开放球权(PLAYING/未 stopped/无定位球)时直接踢走解围;球更深时贴门线站位。
        """
        ctx = self.context
        home = own_goal_area_center(ctx) if ctx is not None else None
        if home is None or self.pose is None:
            self.action = "guard:stop"
            self.stop()
            return

        ball = ctx.ball
        half_l = ctx.field.length / 2.0
        # v2.16(Lead m02385):门将解围后不追球。解围踢出后球若已离开解围半径,
        # 立刻结束 kick 任务回门线站位,避免门将跟着球跑离门口。
        if (
            self._kicking
            and (
                ball is None
                or dist(self.pose.x, self.pose.y, ball.x, ball.y)
                > KEEPER_CLEAR_RADIUS_M + 0.3
            )
        ):
            self.release_kick()
        game = ctx.game
        open_play = (
            game is not None
            and getattr(game, "state", None) is not None
            and getattr(game.state, "name", "") == "PLAYING"
            and not getattr(game, "stopped", False)
            and (getattr(game, "set_play", None) is None or game.set_play == SetPlay.NONE)
        )

        # 门线横移(v2.2):球在己方半场时按 ball.y*0.9 跟随并贴门线站位;
        # 球在对方半场时保守跟随。球比 KEEPER_DEEP_BALL_X 更深时进一步贴线。
        if ball is not None:
            if ball.x < 0.0:
                cover_gain = 1.0  # v2.5:按球 y 全量跟随
                cover_lim = 1.15
                # v2.7:站位 x 不许比 -(half_l-KEEPER_LINE_INSET_M) 更靠外。v2.4
                # 第 4 球的 keeper 追球追到 x=-7.36(门线外)才让球从身侧滚进。
                home = (-(half_l - KEEPER_LINE_INSET_M), home[1])
            else:
                cover_gain = KEEPER_TRACK_GAIN_FAR
                cover_lim = KEEPER_TRACK_Y_LIMIT_FAR
            cover_y = clamp(ball.y * cover_gain, -cover_lim, cover_lim)
            home = (home[0], cover_y)

        # 待命朝向:朝球(便于快速反应);球不可见则朝对方门方向(默认 0)。
        face = 0.0
        if GUARD_FACE_BALL and ball is not None:
            face = angle_to(self.pose.x, self.pose.y, ball.x, ball.y)

        # 门前解围(v2.2):球在解围半径内且开放球权 → 直接踢走,避免被补射/乌龙。
        if ball is not None and open_play:
            d_ball = dist(self.pose.x, self.pose.y, ball.x, ball.y)
            # v3.0 patch2: 门口容差带(|x|>=6.88 且 |y|<=1.6)的活球必须清理,
            # 解围半径放宽 0.5m,避免球卡门线外没人碰。
            in_goal_mouth_band = (
                abs(ball.x) >= GOAL_MOUTH_BAND_X - 0.12
                and abs(ball.y) <= GOAL_MOUTH_BAND_Y
            )
            if d_ball < KEEPER_CLEAR_RADIUS_M or (
                in_goal_mouth_band and d_ball < KEEPER_CLEAR_RADIUS_M + 0.5
            ):
                # v2.7:解围方向固定朝对方半场(禁止朝己方门);仍带 y 校准,
                # 让球踢向中路而不是边线。
                clear_dir = angle_to(
                    ball.x, ball.y, half_l * 0.6, clamp(ball.y * 0.3, -2.0, 2.0)
                )
                self.action = "guard:clear"
                self.kick(clear_dir, KEEPER_CLEAR_POWER)
                return

        # 防 M-05:球在待命点附近但还没到解围半径时,小幅摆动保持"活动"。
        if (
            ball is not None
            and (game is None or not game.stopped)
            and KEEPER_CLEAR_RADIUS_M + 0.4
            < dist(ball.x, ball.y, home[0], home[1])
            < GUARD_INACTIVE_BALL_DIST_M
        ):
            shuffle = int(ctx.now / GUARD_SHUFFLE_PERIOD_S) % 2
            dy = GUARD_SHUFFLE_DIST_M if shuffle == 0 else -GUARD_SHUFFLE_DIST_M
            home = (home[0], clamp(home[1] + dy, -3.6, 3.6))

        self.action = "guard:home"
        debugdraw.point(
            home[0], home[1], rgb=(0.0, 0.6, 1.0), scale=0.2, ns="guard_home",
        )
        self.walk_to(home, face=face, avoid_ball=False, avoid_robots=True)

    def support(self, primary_pose: tuple[float, float] | None = None) -> None:
        """协同支援(v2.0):按进攻/防守两种形态跑位,不再和持球人挤球。

        - 进攻形态(球在对方半场方向,ball.x > -1.5):前插到持球人前方的接应点,
          横向偏移到远离最近对手的一侧,距球 >= SUPPORT_MIN_BALL_DIST_M;
        - 防守形态:退到「球→己方门」连线上,横向让开中路,且不挤进门将区
          (x >= SUPPORT_DEF_MIN_X)。
        线上 1:2 输球 replay 里 19.3% 帧我方两台机器人间距 <1.0m,属于典型
        挤球;支援必须拉开纵深/宽度。
        """
        ctx = self.context
        if ctx is None:
            self.stop()
            return
        ball = ctx.ball
        if ball is None:
            self.stop()
            return
        half_l = ctx.field.length / 2.0
        half_w = ctx.field.width / 2.0
        gx, gy = own_goal(ctx)

        opp_poses: list[Pose2D] = []
        for opp in (ctx.opponents or {}).values():
            if opp.pose is not None:
                opp_poses.append(opp.pose)
        nearest_opp: Pose2D | None = None
        nearest_opp_dist = math.inf
        for op in opp_poses:
            dd = math.hypot(op.x - ball.x, op.y - ball.y)
            if dd < nearest_opp_dist:
                nearest_opp_dist, nearest_opp = dd, op

        side = 1.0 if ball.y >= 0.0 else -1.0
        if nearest_opp is not None and abs(nearest_opp.y - ball.y) > 0.3:
            side = -1.0 if nearest_opp.y > ball.y else 1.0

        if ball.x > SUPPORT_OFFENSE_X:
            # 球已到对方三区:支援改成「拖后接应」(球后方 2.6m、横向 2m)。
            # 线上 v2.0 3:3 复盘:支援按「球前 3.2m」推进时会被边线 clamp 到
            # 对方角旗附近站住,10s 不动吃 inactiveRobot 罚单(robot2 97.8s)。
            tx = ball.x - SUPPORT_TRAIL_M
            ty = ball.y + side * SUPPORT_TRAIL_LATERAL_M
        elif ball.x > -1.5:
            # 进攻支援:前插接应。
            tx = ball.x + SUPPORT_AHEAD_M
            ty = ball.y + side * SUPPORT_LATERAL_M
            # 距球至少 3.2m,避免球停下来后踩 M-05(3m 内 10s 不动罚下)。
            if math.hypot(tx - ball.x, ty - ball.y) < SUPPORT_MIN_BALL_DIST_M:
                away = math.hypot(tx - ball.x, ty - ball.y)
                if away < 1e-6:
                    tx, ty = ball.x + SUPPORT_MIN_BALL_DIST_M, ball.y
                else:
                    k = SUPPORT_MIN_BALL_DIST_M / away
                    tx, ty = ball.x + (tx - ball.x) * k, ball.y + (ty - ball.y) * k
        else:
            # 防守支援:回到球与己方门之间,横向让开中路,不吃门将区。
            ddx, ddy = gx - ball.x, gy - ball.y
            d = math.hypot(ddx, ddy)
            if d < 1e-6:
                ux, uy = -1.0, 0.0
            else:
                ux, uy = ddx / d, ddy / d
            along = min(DEFEND_SUPPORT_DIST_M, d)
            tx = ball.x + ux * along
            ty = ball.y + uy * along
            side = 1.0 if ball.y >= 0.0 else -1.0
            if nearest_opp is not None and abs(nearest_opp.y - ball.y) > 0.3:
                side = -1.0 if nearest_opp.y > ball.y else 1.0
            ty += side * SUPPORT_DEF_LATERAL_M
            tx = max(tx, SUPPORT_DEF_MIN_X)

        # 与 primary(持球人)保持距离,避免两台挤在一点。
        if primary_pose is not None:
            dpm = math.hypot(tx - primary_pose[0], ty - primary_pose[1])
            if dpm < SUPPORT_MIN_MATE_DIST_M:
                pdx, pdy = tx - primary_pose[0], ty - primary_pose[1]
                if dpm < 1e-6:
                    pdx, pdy = 0.0, 1.0
                k = SUPPORT_MIN_MATE_DIST_M / max(dpm, 1e-6)
                tx, ty = primary_pose[0] + pdx * k, primary_pose[1] + pdy * k

        # 任何支援位都尽量离球 >= 3.15m:球停在脚下时站着不动会吃 inactiveRobot。
        d_ball = math.hypot(tx - ball.x, ty - ball.y)
        if d_ball < SUPPORT_MIN_BALL_SAFE_M:
            if d_ball < 1e-6:
                tx, ty = ball.x - SUPPORT_MIN_BALL_SAFE_M, ball.y
            else:
                k = SUPPORT_MIN_BALL_SAFE_M / d_ball
                tx, ty = ball.x + (tx - ball.x) * k, ball.y + (ty - ball.y) * k

        # 到达支援点后球若仍停在附近(比如球被踢向自己),小幅摆动保持活动。
        if self.pose is not None:
            d_here = math.hypot(self.pose.x - ball.x, self.pose.y - ball.y)
            if d_here < GUARD_INACTIVE_BALL_DIST_M:
                shuffle = int(ctx.now / GUARD_SHUFFLE_PERIOD_S) % 2
                dy = GUARD_SHUFFLE_DIST_M if shuffle == 0 else -GUARD_SHUFFLE_DIST_M
                ty = ty + dy

        tx = clamp(tx, -half_l + 0.4, half_l - 0.6)
        ty = clamp(ty, -half_w + 0.5, half_w - 0.5)
        self.move_to_position((tx, ty))

    def take_kickoff(self, kick_target: tuple[float, float] | None = None) -> None:
        """我方开球/重开:未就位则绕到球后待命(避球不碰),就位后接近并踢。"""
        ball = self.context.ball if self.context is not None else None
        if ball is None or self.pose is None:
            self.stop()
            return
        if kick_target is None:
            kick_target = opponent_goal(self.context)
        kick_dir = angle_to(ball.x, ball.y, *kick_target)
        cos_k, sin_k = math.cos(kick_dir), math.sin(kick_dir)
        rel_x, rel_y = self.pose.x - ball.x, self.pose.y - ball.y
        behind = rel_x * cos_k + rel_y * sin_k          # <0 在球后方(己方侧)
        lateral = abs(-rel_x * sin_k + rel_y * cos_k)
        if behind > KICKOFF_FRONT_MARGIN or lateral > KICKOFF_LATERAL_TOL:
            stage = (
                ball.x - cos_k * KICKOFF_STAGE_M,
                ball.y - sin_k * KICKOFF_STAGE_M,
            )
            self.release_kick()
            self.walk_to(stage, face=kick_dir, avoid_ball=True)
        else:
            self.attack(kick_target)

    def move_to_position(self, target: tuple[float, float] | None) -> None:
        """走到站位点(支援/防守/避让),面向球,避球+避机器人。"""
        if target is None:
            self.stop()
            return
        face = None
        ball = self.context.ball if self.context is not None else None
        if ball is not None and self.pose is not None:
            face = angle_to(self.pose.x, self.pose.y, ball.x, ball.y)
        self.release_kick()
        self.walk_to(target, face=face, avoid_ball=True, avoid_robots=True)

    @staticmethod
    def _angular(err: float) -> float:
        return clamp(ANGULAR_GAIN * err, -MAX_ANGULAR, MAX_ANGULAR)
