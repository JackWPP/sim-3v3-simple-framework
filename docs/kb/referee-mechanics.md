# 3v3 仿真自动裁判实现备忘（来自比赛运行时裁判源码）

来源：仿真容器内 `/usr/local/booster_robot/booster_robocup_sim/extensions/game_control/`
（从已退出的 `h5t6r-k1` 容器 docker cp 到 `/tmp/gc/game_control`；基础镜像里没有，
是 Studio 运行时挂载的，重跑 run 后可再拷）。

## 1. 场地与全局阈值（rule_model.py）

- BALL_RESTART_Z=0.11、BALL_RADIUS=0.11、FIELD_LINE_WIDTH=0.05、POSITION_TOLERANCE=0.05
- 场地：14x9，点球区 3x6，球门区 1x4，门宽 2.6、门高 1.8、门深 0.6，中圈 1.5
- 运动判定按速率：DEAD=0.003 m/s，STANDING=DRIFTING=0.15 m/s，YAW_STANDING=0.1 rad/s
- 窗口：READY_STABLE=5000ms，SET 运动窗口=1000ms，STOPPED 运动窗口=2000ms，
  MUST_STOP_GRACE=1500ms，AUTO_START_PLAYING_AFTER_SET=5000ms
- M-04 倒地：FALLEN_DURATION=10000ms、DOT<0.45、HEIGHT<0.25
- M-05 无活动：球 3m 内、10s 内运动��于阈值
- 自由球避让：半径 1.45（=circle_radius-POSITION_TOLERANCE）；豁免=站本方门线
  （|x-goal_x|<=0.05 且 |y|<=1.35）或 500ms 内径向远离球速>=0.05 m/s
- 罚时：30s 起，每计入一次 +15s；罚下时会被 reset 传送出场
- 默认禁用规则：leaving_field、excess_goal_area_defenders、
  excess_kickoff_players_outside_own_half、goal_kick_penalty_area

## 2. 阶段状态机（core.py）

- HALF_DURATION=600s，发布间隔 500ms；kickingTeam=255 表示 None
- SET_PLAY_DURATIONS：noSetPlay{0,0}、kickOff{10,45}、directFreeKick{45,0}、
  indirectFreeKick{45,0}、penaltyKick{60,45}、throwIn{45,0}、goalKick{45,0}、
  cornerKick{45,0}（duration=playing 阶段的球权开放倒计时，readyDuration=ready 阶段上限）
- goal 后：start_set_play(对方, "kickOff") → ready(readyDuration=45) → set(0) →
  playing(kickOff, secondary=10)；主罚触球后 finish_set_play：setPlay=noSetPlay、
  kickingSide=None、secondary=0
- ready→set：双方**全部非罚下机器人**在 5s 窗口内静止（ReadyStabilityTracker）；
  set→playing：固定 5s（仿真开关）
- 出界：仅 playing+not stopped+noSetPlay 判定；|ball_y|-0.135>4.5 边线，
  |ball_x|-0.135>7 门线；由最后触球方对方重启
- 重启位置：throwIn=[clamp(ball_x,±6.95),±4.45]、goalKick=[±6.0,±2.0]、
  cornerKick=[±6.95,±4.45]

## 3. 触球 / 二次触球 / 进球有效性（trackers/set_play.py、restarts.py）

- 需要二次触球才能进球（开球方）：kickOff、indirectFreeKick、throwIn、goalKick
  —— **corner/directFK/penalty 不需要**，角球可直接射门
- touch_count>=2 或（expired 且 first_touch_side != kicking_side）才算满足
- 同一机器人重复触球：需要二次触球的定位球里，球心离上次计数点移动 >=1.5m 才重新计数
- 防守方在主罚触球前触球 → defender_touched_before_kick（R-06 罚下+重踢）
- 自由球避让只在 is_free_kick（不含 kickOff）主罚第一次触球瞬间判定（R-07）
- 乌龙判定：定位球（throwIn/goalKick/corner/direct/indirect）第一脚直接踢进己方门
  → 进球无效，判对方角球

## 4. 我方策略的合规动作清单（v1.1 起）

1. STOPPED（SET/摆球/暂停/无裁判）→ 全员 `stop()`，不碰球
2. READY：走位到合法站位后站住（非开球方：本方半场+圈外；开球方可圈内）
3. 对方开球：门将守门，其余人在本方半场、圈外、距球>3m 等待；球权开放（setPlay
   清空/kickoff 分支结束）后再抢
4. 对方定位球：不 attack；全员距球>1.45m（目标 2.7m 以上），等待点 3.3m 外
   避免 M-05；门将回门线
5. 我方定位球：摆球阶段静止；主罚按类型踢（角球/直接任意球/点球可射门，
   界外球/球门球/间接任意球向前踢，第一脚不朝己方门）；其余人守门+前插接应
6. 开球：主罚朝 +x 踢；非主罚 guard/等待
7. 正常阶段：最近者 attack、次近者 guard（球 3m 内时微移防 M-05）、其余 support(3.5m)
8. 球不可见：全员 stop，不乱走
