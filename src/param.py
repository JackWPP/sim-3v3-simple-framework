"""集中调参入口。

这里放策略、走位、踢球和避障的可调参数。数值迁移自当前代码文件,
以后优先在本文件调整参数。
"""

from __future__ import annotations

import math


# ======================================================================
# 踢球力度
# ======================================================================

# Player.kick() 会把力度夹到这个范围内。如果超过范围，因为控制接口不支持，可能会摔倒。
KICK_POWER_MIN = 1.0
KICK_POWER_MAX = 10.0

# 普通比赛踢球力度。
KICK_POWER_DEFAULT = 5.0
# 射门力度随距门距离线性增长:power = clamp(BASE + PER_M * 距门距离, BASE, CAP)。
# 门前轻推避免打飞,远射加大力度;上限 8.5 防止高力度踢球摔倒。
KICK_POWER_BASE = 4.5
KICK_POWER_PER_M = 0.5
KICK_POWER_CAP = 8.0
KICK_POWER_BACKFIELD = 5.0
KICK_POWER_OUR_KICKOFF = 5.0
KICK_POWER_OUR_KICKOFF_PASS = 4.2  # 开球第一脚短传给队友(直接射门无效:G-05 需二次触球)


# 定位球:向前场踢出(界外球/球门球/间接任意球)的力度。
# iteration-12 实测 8.0 会把球直接踢出边线(单场 8 次 throwIn + 3 次 goalKick),
# 降到 5.5 只求稳稳推进、把球留在场内。
KICK_POWER_SET_PLAY_FORWARD = 5.0
# 定位球:可以直接射门的类型(角球/直接任意球/点球)的射门力度。
KICK_POWER_SET_PLAY_SHOT = 8.0
KICK_POWER_SET_PLAY_PASS = 3.6   # 需二次触球的定位球(界外球/球门球/间接任意球)第一脚短传给队友

# 我方定位球:向前推进的目标距离(m),以及目标点离边线/底线的安全余量(m)。
SET_PLAY_FORWARD_M = 4.0
SET_PLAY_TARGET_MARGIN_M = 1.2


# ======================================================================
# Player 走位控制
# ======================================================================

ARRIVE_DIST = 0.15             # 到达目标点阈值 (m)
OMNI_DIST = 1.0                # 距目标小于该值时使用全向近距控制
TURN_THRESHOLD = 0.5           # 远距离行走时,角差超过该值先原地转向 (rad)
# iteration-12 实测 2.0 在挤堆时摔倒/碰撞明显,先降到 1.8 观察。
MAX_LINEAR = 1.8               # 指令前进速度上限 (m/s)
MAX_ANGULAR = 2.0              # 指令转向速度上限 (rad/s)
LINEAR_GAIN = 1.5              # 平移 P 增益
ANGULAR_GAIN = 2.0             # 转向 P 增益


# ======================================================================
# Player 踢球 / 射门规划
# ======================================================================

# v2.8:回退 v2.7 ③。第 3 场 0:6 回归证实「对齐门控 + ENTER 1.0」导致 kick 任务
# 反复起停(105 次尝试、54% 成功、场均 kick 活动帧减半),我方球在己方三区 70.5%、
# 对方三区触球 0。恢复 v2.6 的 ENTER/EXIT 与直接 kick。
KICK_ENTER_M = 2.0             # 距球小于该值进入踢球状态
KICK_EXIT_M = 2.5              # 踢球中距球大于该值才退出踢球状态
CHASE_BEHIND_M = 0.35          # 追球时站到球后方的距离


# ======================================================================
# Player 技术动作参数：守门 / 支援 
# ======================================================================

GUARD_FACE_BALL = True
GUARD_THREAT_ENTER_X = -1.0
GUARD_THREAT_EXIT_X = -0.7

SUPPORT_DIST_M = 3.5           # 支援点距球距离；必须 >3m,否则会踩 M-05(3m 内 10s 不动)罚下
SUPPORT_SEPARATION_M = 1.8     # 支援点与更靠前的队友的最小距离,避免三台挤在一点被撞倒

# ======================================================================
# Normal 阶段策略
# ======================================================================

ATTACKER_KEEP_DIST_MARGIN_M = 0.3  # 防止 Attacker 选择产生震荡

FALLEN_COST = 10.0  # 摔倒球员的距离惩罚值(米)


# ======================================================================
# 开球 / 定位球策略
# ======================================================================

# 开球
KICKOFF_STAGE_M = 2.0
KICKOFF_FRONT_MARGIN = 0.1
KICKOFF_LATERAL_TOL = 0.35

CENTER_LEAVE_DIST_M = 0.15 # 球离开中心点多少距离，认为球已经动了

OPP_SET_WALL_DIST_M = 2.0 # 对方开球时，在多少距离之后阻挡


# ======================================================================
# 裁判规则安全距离（实现依据见 docs/kb/referee-mechanics.md）
# ======================================================================

# 对方定位球：防守方在踢球方触球瞬间距球必须 >1.45m(规则判定线,不能低于)。
RESTART_AVOID_RADIUS_M = 1.45
# 防守时与球保持的目标距离(规则线+余量)。
SET_PLAY_DEF_GAP_M = 2.7
# 防守等待点距球距离；>3m 避开 M-05(球 3m 内 10s 不动罚下)。
SET_PLAY_DEF_SAFE_DIST_M = 3.3

# v2.15:对方定位球防守「径向先行 + 逐帧闭环」(analyst 第 9 场 d1ebca78 复盘,
# Lead m01991)。第 9 场两张罚单(R-06 defender_set_play_interference@460.02、
# R-07 illegalPosition 1.005m@553.0)根因:等待点 _defender_set_play_spot 落在
# 球的另一侧,机器人从摆球期位置直线走过去时路径穿球。现在:
#   - _act_stopped:撤离触发 1.45+0.35=1.8 → 2.3m,撤离目标 2.0 → 2.6m;
#   - _act_opp_set_play:等待时先沿「球→机器人」径向绕到球对侧,在半径 2.6m
#     的圆弧上逐步推进(弦线离球最近 2.48m),每帧保证非门将距球≥1.7m。
STOP_VACATE_TRIGGER_M = 2.3
STOP_VACATE_TARGET_M = 2.6
SET_PLAY_DEF_ORBIT_RADIUS_M = 2.6
SET_PLAY_DEF_MIN_CLEAR_M = 1.7
# 对方开球时等待点距球距离；中圈半径 1.5,必须 >1.55 且在 >3m 外避开 M-05。
OPP_KICKOFF_WAIT_RADIUS_M = 3.2
# 门将退到门线附近时距门线的距离(m)。
KEEPER_GOAL_LINE_INSET_M = 0.15
# 门将站在门线附近时允许的 |y| 上限(门半宽 1.3,留余量)。
KEEPER_GOAL_LINE_Y_LIMIT_M = 1.2
# 门将待命点距球小于该值时做微移,避免 M-05。
GUARD_INACTIVE_BALL_DIST_M = 2.9
GUARD_SHUFFLE_DIST_M = 0.35
GUARD_SHUFFLE_PERIOD_S = 2.5
# 裁判 stopped(摆球)后允许移动的宽限期(裁判 MUST_STOP_GRACE_MS=1500)；只在这段时间内
# 把离重启点太近的机器人撤离，之后必须完全静止，否则踩 stopped_motion(M-02)。
# 注意:GameControl 发布间隔 500ms，我方看到 stopped 可能已晚 0~0.5s，所以这里只留
# 0.7s(1.5 - 0.5 延迟 - 0.3 余量)，实测 1.2s 会在 2.7s 处被判定移动 0.45m 罚下。
STOP_GRACE_MOVE_S = 0.0
# 全向撤离(不转身)的最大平移速度(m/s)。
OMNI_ESCAPE_SPEED = 1.2
LINE_HOLD_MAX_S = 6.0        # 球贴边线时最多保持距离等待的时间,超时改为向场内解围
KICK_POWER_LINE_CLEAR = 4.5  # 贴边线活球解围(向场内)力度

# ======================================================================
# 协同进攻(v2.0):推进/射门选择与支援跑位
# ======================================================================
# 距对方球门该距离内才直接射门;更远时改为短推带球推进,避免无意义大脚把
# 球权直接交还对方(线上 replay 实测:从任何位置都朝门开大脚,导致球权快速丢失)。
SHOOT_RANGE_M = 6.5
# 射门基础力度(再加距离修正,上限 KICK_POWER_CAP)。
KICK_POWER_SHOOT_BASE = 5.0
# 射门瞄准点离门柱内侧的距离(m),门半宽 1.3。
SHOOT_TARGET_INSET_M = 0.45
# 一次推进(带球)把球往前送的理想距离(m)与力度。
PROGRESS_AHEAD_M = 3.0
KICK_POWER_DRIBBLE = 4.2
# 己方半场被逼抢时的解围力度。
KICK_POWER_CLEAR = 6.5
# 支援球员(非门将、非持球人)站位参数。
SUPPORT_AHEAD_M = 3.2      # 进攻时前插到球前方该距离
SUPPORT_LATERAL_M = 2.5    # 进攻支援的横向偏移(选远离最近对手一侧)
SUPPORT_MIN_BALL_DIST_M = 3.2  # 支援点距球至少这么远(避免 M-05 无活动判罚)
SUPPORT_MIN_MATE_DIST_M = 2.0  # 与 primary 至少这么远(避免挤在一起)
DEFEND_SUPPORT_DIST_M = 3.0    # 防守时退到球→己方门连线上该距离
SUPPORT_DEF_MIN_X = -5.2       # 防守支援的最深 x(不要挤进门将区)
SUPPORT_DEF_LATERAL_M = 1.5    # 防守支援的横向偏移


# 我方定位球：主罚距球小于该距离开始踢。
SET_PLAY_NEAR_BALL_M = 2.2
# 我方定位球：接应队员前插距离。
SET_PLAY_RECEIVER_AHEAD_M = 3.5
# v2.6:主罚选择改为「到球后方接近点最近」者,接近点=ball-kick_dir*该距离(m),
# 阶段内保留原主罚的额外宽容距离(m),避免贴边线球绕不过来/首触慢。
# v2.14:1.0→0.5(analyst+Lead:第7场定位球首触中位 12.2s、25 条里 22 条 >3s,
# 绕后 1.0m 太远;缩短接近点让主罚更快触球,配合 avoid_ball=False)。
SET_PLAY_TAKER_APPROACH_M = 0.5
SET_PLAY_TAKER_KEEP_MARGIN_M = 0.6
# v2.6:二次触球定位球的短传力度按距离插值,不再固定 3.6;
# 线上 20c6a6cb 第 1 球就是固定力度短传被罚下队友、落点朝己门滚 8.2m 乌龙。
SET_PLAY_PASS_POWER_BASE = 3.0
SET_PLAY_PASS_POWER_PER_M = 0.25
SET_PLAY_PASS_POWER_MIN = 3.0
SET_PLAY_PASS_POWER_MAX = 4.5
# v2.7:间接球第一脚禁止「直接/折射进门被判无效」:落点距对方门线至少该值(m),
# 且离「球→对方门中心」的射门线至少 SET_PLAY_PASS_OFFLINE_M(m);没有合格队友时
# 改为朝中路的横向轻推,力度 <=3.5。
SET_PLAY_PASS_GOAL_LINE_GAP_M = 2.0
SET_PLAY_PASS_OFFLINE_M = 1.0
SET_PLAY_LATERAL_POWER = 3.2
# v2.14:定位球第一脚落点距最近对手至少该值(m),避免传到被对手站住的中场
# (analyst 第 7 场复盘:界外球/门球第一脚多次直接送给对手形成远射)。
SET_PLAY_PASS_OPP_CLEAR_M = 1.6

# ======================================================================
# 站位 / 避让
# ======================================================================

OPPONENT_RESTART_AVOID_M = 1.65
CIRCLE_MARGIN_M = 0.3


# ======================================================================
# 踢球目标几何
# ======================================================================

GOAL_TARGET_DEPTH_M = 0.25              # 踢球目标点在球门内的深度 (m)

# ======================================================================
# 障碍物几何参数
# ======================================================================

BALL_OBSTACLE_RADIUS = 0.5              # 球的障碍半径 (m)；用于避障计算
OPPONENT_RADIUS = 0.55                  # 对手机器人半径 (m)
TEAMMATE_RADIUS = 0.48                  # 队友机器人半径 (m)
SAFETY_MARGIN = 0.22                    # 通用安全余量 (m)

GOAL_DEPTH = 0.6                        # 球门深度 (m)；用于球门障碍建模
POST_RADIUS = 0.18                      # 门柱半径 (m)
NET_RADIUS = 0.20                       # 球网半径 (m)
NET_STEP = 0.35                         # 球网离散化步长 (m)

START_IGNORE = 0.0                      # 起点忽略半径 (m)；起点附近障碍不参与规划
TARGET_IGNORE = 0.0                     # 终点忽略半径 (m)；终点附近障碍不参与规划

# ======================================================================
# 全局路径规划器 (A* Grid Planner)
# ======================================================================

USE_GLOBAL_PATH_PLANNER = True          # 是否启用全局规划器；False 时回退到局部 VFH
GLOBAL_GRID_RESOLUTION_M = 0.35         # 栅格分辨率 (m/格)；越小路径越精细，但计算量越大
GLOBAL_FIELD_MARGIN_M = 0.25            # 场地边界外扩余量 (m)；确保边界附近路径可行
GLOBAL_OBSTACLE_MARGIN_M = 0.10         # 障碍物膨胀余量 (m)；在障碍半径上额外扩大多少
GLOBAL_PATH_LOOKAHEAD_M = 0.9           # 从规划路径中提取前方多远的路径点 (m)

# ======================================================================
# 局部路径规划器 (VFH Direction Scan)
# ======================================================================

PLAN_LOOKAHEAD = 1.2                    # 前方探测射线长度 (m)；规划器"看"的范围
PLAN_CLEARANCE = 0.35                   # 最小安全余量 (m)；候选方向前方必须大于此值
PLAN_STEP = math.radians(15)            # 候选方向扫描步长 (rad)；越小方向越精细
PLAN_MAX_OFFSET = math.radians(100)     # 最大偏离目标方向的角度 (rad)；扫描范围 ± 该值

# ======================================================================
# 可视化
# ======================================================================

KICK_TARGET_MARK_SIZE_M = 0.18

# ---- v2.1 线上复盘后调整:门将封角度 / 支援纵深 / 射门收敛 ----
# 线上 v2.0 首战 3:3:三个失球都是球横穿门线时门将 y 还停在旧位置(门将只按
# ball.y*0.65 跟,球一旦被折射/横传就来不及)。改为球在己方半场时按球 y 直接
# 跟随(0.9 倍),并把门将站位推到门线内侧 0.2m。
KEEPER_LINE_INSET_M = 0.2
KEEPER_TRACK_GAIN_OWN_HALF = 0.9
KEEPER_TRACK_GAIN_FAR = 0.5
KEEPER_TRACK_Y_LIMIT_OWN = 1.2
KEEPER_TRACK_Y_LIMIT_FAR = 0.8
# 进攻支援:球已进入对方三区(x>2.5)时,支援改为「拖后接应」而不是继续前插
# (前插会被边线 clamp 后停在对方角旗附近,10s 不动吃 inactiveRobot 罚单)。
SUPPORT_TRAIL_M = 2.6
SUPPORT_TRAIL_LATERAL_M = 2.0
SUPPORT_OFFENSE_X = 1.5
SUPPORT_MIN_BALL_SAFE_M = 3.15
# 射门收敛:瞄得更靠门内(0.45),上限力度 7.5,减少打飞/打偏出底线。
SHOOT_POWER_MAX = 7.5     # 射门力度上限(降低打飞出底线概率)

# v2.2:门将出击解围 + 关键站位修正
# 线上 v2.1 首战 0:1(阿白):门将 walk_to 带了 avoid_ball=True,当球滚到门前
# (门将目标≈球位置)时避球力把门将往反方向推,球从门线横穿时门将反而后退。
KEEPER_CLEAR_RADIUS_M = 1.35   # 球进入该半径内门将直接踢走(解围)
KEEPER_CLEAR_POWER = 6.0       # 解围力度
KEEPER_DEEP_BALL_X = -5.0      # 球比这更深时门将贴门线站位
KEEPER_DEEP_INSET_M = 0.1      # 贴线时离门线距离

# v2.2:对方定位球摆球期间的撤离节奏。
# 裁判 MUST_STOP_GRACE_MS=1500 内移动不罚,宽限后 2s 窗口位移 >0.3m 才罚 M-02。
# v2.6:线上 20c6a6cb 3 次 stopped_motion(sim 204/521/670s,位移 0.301-0.330m)全部
# 发生在对方 throwIn 摆球期:根因是窗口结束后只 continue、不发零速度,残留的
# 1.5m/s 指令让机器人继续滑行过阈值。改为窗口 0.6→0.35、速度 1.5→1.0,
# 并在窗口结束后对所有人显式 p.stop()(见 main._act_stopped)。
# v2.8:窗口 0.35→1.15。analyst 复盘 60d19472:0.35s@1.0 快撤 + 0.12 爬行跨过
# 1.5s 静止宽限,2s 窗口累计 0.332m>0.3m 吃 stopped_motion(M-02)。改在宽限内
# (1.15s@1.0m/s)一次撤完,窗口后硬停,同时满足 R-07 避让与 M-02 静止。
# v2.13:窗口 1.15→0.5。v2.12 线上 3083b42e 复现 stopped_motion(0.333m/2.69s,
# throwIn stopped 期):1.15s 窗口本身占掉裁判 1.5s 静止宽限的大半,窗口末仍
# 以 1.0m/s 滑行易累计超 0.3m。0.5s@1.0m/s=0.5m 撤出仍在 1.5s 宽限内完成,
# 余下 1.0s 硬停,位移余量足够(v2.6 0.35s 窗口线上无罚单)。
STOP_VACATE_WINDOW_S = 0.5
STOP_VACATE_SPEED = 1.0
# v2.6:GameControl 状态发布有 0~0.5s 延迟,记录 stopped_since 时回拨该补偿,
# 让宽限窗口对齐裁判的真实计时点(否则宽限整体右移、刹车指令发晚)。
# v2.16:0.35→1.15(analyst 第 10 场 0116ec1d 复盘)。M-02 真实判定窗只有 0.96s
# (reference 116.89→传送 117.85),0.3348m≈0.35m/s 是「0.5s@1.0m/s 快撤残余段」
# 跨过 grace;crawl 只贡献约 0.1m。回拨 1.15s 后,检测到 stopped 时 elapsed 已
# 超过窗口 → 直接走 crawl(0.10m/s),首个判定窗内位移约 0.1m<0.3m。
STOP_STATE_LATENCY_COMP_S = 1.15
# v2.8:慢爬归零(窗口已延长到 1.15s,足够撤出 1.45m 风险圈),窗口后一律硬停。
# v2.14:0.0→0.12。v2.13 窗口 0.5s 快撤后硬停,线上 d1ebca78 第 9 场仍吃 2 张
# 定位球防守罚单(defender_set_play_interference + illegalPosition 1.005m<1.45);
# 盘带期径向慢爬远离满足 R-07 的「径向远离」豁免,0.12m/s 在 M-02 的 2s 观察窗
# 内仅 0.24m<0.3m。
# v2.15:0.12→0.10。线上 0116ec1d 第 10 场 stopped_motion 0.3348m/2372ms
# (v2.14 crawl 0.12m/s×2.37s≈0.285m + 残余速度,越 0.3m 阈值);0.10m/s 在
# 2.4s 内仅 0.24m<0.3m,仍满足 R-07「径向远离」豁免(≥0.05m/s)。
STOP_CRAWL_SPEED = 0.10
# v2.7:活球「站桩」修复(P0)。球几乎静止且我方非门将无人进入 1.2m 时,
# 强制最近的非门将去抢(绕过 support/粘滞选择)。线上 dffb89db/b4c9a02e
# 复盘:球静止 2-4s、最近人 0.74-0.83m 站着不抢,白给对手断球/补射。
PRESSER_STALL_SPEED_MPS = 0.2
# v2.12: 1.2→1.8(Lead):球停且最近者仍远时更早强制施压,避免全员看着静止球。
# v2.13: 回退 1.8→1.2(Lead)。第8场 1:2 负弱队,presser 1.8 让更多回合由
# "最近者强跑"接管,阵型被拉散(ball_in_home_half 60.6% vs v2.11 38.2%);
# 先恢复 v2.11 行为,P0-a 三区解围保留待复盘判读。
PRESSER_TRIGGER_DIST_M = 1.2

# v2.12: 己方三区直接解围(Lead/analyst:第7场两个失球同型——己方三区静止球,
# 我方最近者绕位1.5s不触球,对手0.35m先捅)。x < 该值即视为己方三区。
OWN_THIRD_CLEAR_BALL_X = -3.5
# v2.12: 死球解围时先站到球的门侧,再起脚。
PRESSER_DEADBALL_APPROACH_M = 0.45

# v2.12(P1): 清球落点改朝边线(避免中路送二点/底线送对方门球)。
# 落点 x = half_l - KICK_CLEAR_TARGET_X_FROM_GOAL,y = ±(half_w - 该余量)。
KICK_CLEAR_TARGET_X_FROM_GOAL = 2.2
KICK_CLEAR_LATERAL_MARGIN_M = 0.2

# v2.9:开球期非主罚不得原地 stay 站桩。第 4 场 f751146f 我方 7 张罚单全部
# inactiveRobot:开球 phase 里非主罚按旧逻辑 stop() 站住,主罚触球后球滚到
# robot1 脚边 0.31m 停住,10s 后三台陆续吃 inactiveRobot。改为每帧检查:
# 球距自己 <3.2m 或球正向我方半场滚动(vx<0)时,主动退到安全点并保持走位。
KICKOFF_STAY_SAFE_DIST_M = 3.2
KICKOFF_SAFE_X = -2.5
KICKOFF_SAFE_Y = 2.6
KICKOFF_DEEP_SAFE_X = -4.0
KICKOFF_DEEP_SAFE_Y = 2.0
KICKOFF_BALL_TOWARD_HALF_VX = -0.05

# v2.10:数据缺失(game/ball 为 None)时的防御性慢速巡逻。第 4 场 f751146f
# 288–305s 出现「三台同时 0 指令、球旁 0.31m 站 10s+」→ inactiveRobot;根因
# 候选是 context.game/ball 短暂丢失后 play() 走进全员 stop() 分支(或 play 抛
# 异常被 framework 兜底全员停车)。数据缺失 ≠ 裁判暂停:改为慢速小幅巡逻,
# 0.12m/s × 2s = 0.24m < M-02 的 0.3m 阈值,同时又足够让平台判为「在动」。
DATA_LOSS_PATROL_SPEED = 0.12     # m/s;任意 2s 窗口位移 ≤0.24m
DATA_LOSS_PATROL_STEP_M = 0.6     # 巡逻目标点相对自身的距离
DATA_LOSS_PATROL_FLIP_S = 2.0     # 换向周期(s)
DATA_LOSS_APPROACH_M = 1.2        # 距最后已知球位小于该值后转入巡逻
