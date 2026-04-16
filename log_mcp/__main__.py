"""
CLI 入口：解析 --config 参数，启动 MCP Server。
"""

import argparse
import asyncio
import logging

from .server import run_server


def main() -> None:
    # 日志输出到 stderr，避免污染 stdio transport
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        prog="log-mcp",
        description="LOG MCP Server —— 通用日志查询 MCP Server",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="sources.yaml 配置文件路径；不指定则以纯动态注册模式启动",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="开启 DEBUG 日志",
    )
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    asyncio.run(run_server(args.config))


if __name__ == "__main__":
    main()
