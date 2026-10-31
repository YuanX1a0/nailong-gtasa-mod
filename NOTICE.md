# 第三方署名 / Third-Party Attribution

## 原始 Blender 模型

- 作者：**WeDai**
- 仓库：<https://github.com/bigdiu/naiwa-nailoong-blender-model>
- 文件：`nailong_colored.blend`（34,021 顶点 / 33,980 面，4 个程序化材质）
- 原仓库声明：模型供学习、练习使用；角色版权不属该仓库；请勿商用；
  转载 / 二次分享请保留仓库链接与作者署名。

本项目使用了该 .blend 文件作为唯一输入，做了以下修改：

1. 坐标轴转换：Blender Z-up 映射为 SA ped 轴向（X=上 / Y=前 / Z=左右），
   整体缩放到与基准 ped `WM1.dff` 等高（1.93）。
2. 几何处理：拆分眼睛/嘴部壳体 → 身体封孔 → 体素重构（voxel 0.008）
   → 减面到 9,000 面；眼睛/嘴保留独立壳体并减至 1,800 面。
3. 蒙皮：身体使用 32 根标准 SA ped 骨骼自动热力权重；眼睛/嘴刚性绑定 `" Head"`。
4. 贴图：原程序化材质（基于 Generated 坐标的 62 个 MATH 节点）烘焙为
   1024×1024 贴图 `nailong_baked.png`，打包进 `nailong.txd`。
5. 顶点色：移除全部顶点色层，避免 SA 将其作为 prelight 导致模型发暗。

## 角色版权

「奶龙 / Nailoong」角色形象的版权归其原作者 / 版权方所有。
本仓库仅提供面向 GTA:SA 的技术格式转换，不声称拥有角色版权，且不允许商业使用。

## 工具

- Blender 5.0 + [DragonFF](https://github.com/Parik27/DragonFF)（DFF/TXD 导入导出）
- 皮肤 ID → 模型名对照表参考 SA-MP 社区皮肤列表
