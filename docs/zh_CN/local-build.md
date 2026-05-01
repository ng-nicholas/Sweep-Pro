# Sweep-Pro 本地编译

本文记录在本机编译 Sweep-Pro ZMK 固件的流程。先按你的实际 checkout 位置设置 `NXTKB_ROOT`：

```shell
export NXTKB_ROOT="/path/to/nxtkb"
cd "$NXTKB_ROOT/zmkfirmware/zmk"
```

后续命令默认从 ZMK workspace 根目录执行。`$NXTKB_ROOT/Sweep-Pro` 是键盘配置和 shield 仓库，不是 west workspace 根目录。不要在 `Sweep-Pro` 目录里直接执行 `west build`。

当前本地编译使用官方 `zmkfirmware/zmk` checkout。Sweep-Pro 的屏幕状态栏已经从旧的 `lynnlee0522/zmk` fork 拆成独立模块 `zmk-vfx-sweep-pro-display`，所以编译带屏幕的左手固件时需要同时加入该 module，并把 `sweep_display` 放进 `SHIELD` 列表。

## 依赖

本机需要先准备系统构建工具、Zephyr SDK 和 `uv`。

Arch Linux 示例：

```shell
sudo pacman -S git cmake ninja gperf ccache dfu-util dtc wget \
    tk xz file make uv
```

Zephyr SDK 可以通过 AUR 安装，或按 ZMK/Zephyr 官方文档手动安装：

```shell
paru -S zephyr-sdk
```

如果 SDK 没有被自动识别，可以在当前 shell 里指定：

```shell
export ZEPHYR_TOOLCHAIN_VARIANT=zephyr
export ZEPHYR_SDK_INSTALL_DIR="$HOME/zephyr-sdk-0.17.0"
```

## 初始化 Python 环境

在 ZMK workspace 根目录创建项目内虚拟环境：

```shell
export NXTKB_ROOT="/path/to/nxtkb"
cd "$NXTKB_ROOT/zmkfirmware/zmk"
uv venv --python 3.13
source .venv/bin/activate
uv pip install west
```

每次新开终端编译前，都需要重新激活虚拟环境：

```shell
export NXTKB_ROOT="/path/to/nxtkb"
cd "$NXTKB_ROOT/zmkfirmware/zmk"
source .venv/bin/activate
```

## 初始化 west workspace

第一次配置这个 checkout 时执行：

```shell
west init -l app/
west update
west zephyr-export
uv pip install -r zephyr/scripts/requirements-base.txt protobuf
```

`west zephyr-export` 会写入用户级 CMake package registry；`west update` 和 `uv pip install` 需要联网。

## 编译 Sweep-Pro

公共参数：

```shell
export NXTKB_ROOT="/path/to/nxtkb"
EXTRA_MODULES="$NXTKB_ROOT/Sweep-Pro;$NXTKB_ROOT/zmk-vfx-sweep-pro-display;$NXTKB_ROOT/cirque-input-module;$NXTKB_ROOT/zmk-behavior-report;$NXTKB_ROOT/zmk-behavior-send-string"
ZMK_CONFIG_DIR="$NXTKB_ROOT/Sweep-Pro/config"
```

左手带屏幕编译时使用组合 shield：`sweep_left` 提供键盘本体和屏幕硬件节点，`sweep_display` 提供自定义状态栏 UI。建议同时启用 USB logging 和 Studio RPC over USB UART，方便调试：

```shell
west build -s app -p -d build/sweep_left -b nice_nano//zmk \
    -S zmk-usb-logging -S studio-rpc-usb-uart -- \
    -DSHIELD="sweep_left sweep_display" \
    -DZMK_EXTRA_MODULES="$EXTRA_MODULES" \
    -DZMK_CONFIG="$ZMK_CONFIG_DIR"
```

如果只想编译不带屏幕状态栏的左手固件，可以把 `-DSHIELD` 改回 `sweep_left`。

右手：

```shell
west build -s app -p -d build/sweep_right -b nice_nano//zmk -- \
    -DSHIELD=sweep_right \
    -DZMK_EXTRA_MODULES="$EXTRA_MODULES" \
    -DZMK_CONFIG="$ZMK_CONFIG_DIR"
```

这里显式使用 `-s app`，因为当前目录是 workspace 根目录，ZMK 应用源码在 `app/` 下。

构建成功后，固件位于：

```text
build/sweep_left/zephyr/zmk.uf2
build/sweep_right/zephyr/zmk.uf2
```

第二次编译同一个 build 目录时，如果 CMake 参数没有变化，可以直接执行：

```shell
west build -d build/sweep_left
west build -d build/sweep_right
```

修改了 shield、extra modules、snippets 或 `ZMK_CONFIG` 后，建议继续使用带 `-p` 的完整命令重新生成构建目录。

## 常见问题

如果看到：

```text
west: unknown command "build"; do you need to run this inside a workspace?
```

说明当前目录不是 west workspace，回到：

```shell
export NXTKB_ROOT="/path/to/nxtkb"
cd "$NXTKB_ROOT/zmkfirmware/zmk"
source .venv/bin/activate
```

如果看到：

```text
source directory "." does not contain a CMakeLists.txt
```

说明命令从 workspace 根目录执行时缺少 `-s app`。

右手构建可能出现一些 Kconfig 提示，例如 USB、display widget 或 smooth scrolling 的配置被 split peripheral 角色关闭。这类提示来自左右手角色差异；只要最终生成 `zmk.uf2`，构建就是成功的。
