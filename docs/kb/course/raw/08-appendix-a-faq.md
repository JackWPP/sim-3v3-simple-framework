# 补充-常见问题与优化方向

## 常见问题

### `set_velocity` 静默跳过 → "机器人不动"

`set_velocity`（`player.py`）只有在 `mode == "walk"` 且非踢球中才真正生效。`walk_to` 开头会 `release_kick()`（`player.py`），但如果你在 `ensure_ready()` 返回 `False`（摔倒/还没切到 `walk` 模式）时直接发速度指令，它会被忽略而不报错——表现为"机器人原地不动，日志也平静"。

排查：先确认 `p.ensure_ready()` 返回 `True`、且 `p.mode == "walk"`，再下速度指令。

### `_act_ready` 用列表下标分站位，有人罚下会错位

`_act_ready`（`main.py`）用 `players[0]/[1]/[2]` 下标分配三个站位。若某个球员被罚下（`is_penalized`），`active` 列表只剩 2 人，`players[2]` 越界或站位错配。

修复：用 `player.id` 而非下标分配；或用 `for i, p in enumerate(players)` 配合字典映射。

### `param.py` 死参数，改了无效

部分参数声明了但当前代码未引用：如 `KICK_POWER_BACKFIELD`、`GUARD_THREAT_ENTER_X`/`EXIT_X`、`CENTER_LEAVE_DIST_M`、`OPPONENT_RESTART_AVOID_M`、`CIRCLE_MARGIN_M` 等。改它们看不到任何效果，还容易让你误以为"调参没用"。

排查：调参前 `grep -rn "参数名" src/` 确认被引用。

### 预留未用 API

以下方法/函数已实现但默认策略未调用，属于"可解锁技能"：

- `take_kickoff()`（`player.py`）：开球走位逻辑，但 `_act_our_kickoff` 目前直接用 `kick()` 没调用它。
- `kick_can_score()`（`player.py`）：判断某方向能否进球，可用于选射门点。
- `block_path_projection()`（`player.py`）：算自己到"对手→球"线段垂足，用于封堵。
- `detour()`（`utils/obstacles.py`）：单障碍绕行 via 点，可用于精细走位。

### 忘记 `init_store` 初始化字段

在 `play()` 里访问 `store.xxx` 但没在 `init_store` 声明，第一次会靠 `getattr(store, "xxx", None)` 兜底（`main.py`），但后续逻辑若假设它已是某种类型（如 list），仍可能出错。习惯：在 `init_store` 里集中声明所有要用到的字段。

### 对手发球时，我方 `_act_normal` 仍去抢球导致被罚下 ⚠️

当裁判机进入对方的开球或定位球阶段（`OPP_KICKOFF` / `OPP_SET_PLAY`）时，规则要求我方球员必须退到一定距离外、不能触碰球。但 `_act_opp_kickoff` 目前只让一人守门、其余退到中圈外；而 `_act_opp_set_play` 现在直接调了 `_act_normal`——这意味着进入对方定位球时，我方球员会照常去 `attack()` 抢球，一旦碰到球就会被裁判机判罚下场，少打一人。

修复思路：确保 `OPP_SET_PLAY` 阶段绝不调用会主动触球的 `attack()`/`support()`。改为全员退守、区域站位或随球移动但不触球（用 `walk_to(..., avoid_ball=True)` 且到达后 `stop()`）。第 9 篇已给出 `OPP_SET_PLAY` 的人墙/联防模板，注意里面都只做走位、不主动踢球。一个稳妥的判断是：

```Python
# 在 _act_opp_set_play 里，永远不要直接调 _act_normal
def _act_opp_set_play(context, players, store):
    # 根据 get_set_play_type 分派到"只走位、不触球"的防守函数
    ...
    # 任何分支里都用 walk_to + stop，不要 attack()
```

> 💡 这条坑是实战里最容易翻车的一条——很多队伍正常拼抢很强，但一遇到对方任意球就莫名少人。请务必把 `OPP_SET_PLAY` 的"不触球"原则刻进肌肉记忆。

> 此步骤可借助AI Assistant完成，参考提示词：请帮我修复 \_act_opp_set_play 中“对方发球时仍调用 \_act_normal 导致抢球被罚下”的问题，改为按 get_set_play_type 分派到只走位、不触球的防守函数（全程 walk_to + stop，不调用 attack()）。

---

## 优化方向提示

> 挑 2\~3 个先做就能显著提分。

1. 角色分配打分：当前按"离球最近 / 离门最近"简单分派；可改为基于态势打分（谁更快到达球、谁的射门角度更好、谁更适合当前角色），用 `store` 记录评分。
2. 走位与避障：A\*/VFH 参数已可调；可加动态避障权重、队友协同让路、对持球对手的压迫路线。
3. 射门选点：`plan_kick()` 当前踢向门中心；可改为选门内最大空当 / 避开守门员，或结合比分选稳妥/冒险（用 `kick_can_score()` 校验）。
4. 开球与定位球：补全 `OUR`/`OPP_SET_PLAY` 留白，设计传切配合、假动作、二次进攻。
5. 分区与阵型：按球所在区域切换整体压上 / 回收；结合 `Phase` 做更细的战术阶段机。
6. 参数自适应：根据比分、剩余时间、对手强度动态调整 `SUPPORT_DIST_M`/`MAX_LINEAR` 等。
7. 守门逻辑：增强 `guard` 的预判与出击时机，危险区主动前压断球。
8. 跨帧战术：用 `store` 实现多阶段战术。
9. 对手建模：读 `opponents` 状态做预测，提前布防。