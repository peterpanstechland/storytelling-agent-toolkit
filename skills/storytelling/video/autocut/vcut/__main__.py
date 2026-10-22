"""python -m vcut  （由 video/run autocut 调用）"""
import sys

try:
    from .cli import main
except ImportError as exc:  # 缺基础依赖时给出明确提示，而不是一长串 traceback
    print(f"autocut 缺少依赖：{exc}\n请先在你自己的环境里安装：python -m pip install -r video/requirements-autocut.txt",
          file=sys.stderr)
    sys.exit(2)

if __name__ == "__main__":
    main()
