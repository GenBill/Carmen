#!/usr/bin/env python3
"""加仓点位与股数计算：5 笔等额资金，模式 A / 模式 B。"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


TRANCHES = 5
TRANCHES_A = 6
DEFAULT_MD_PATH = Path(__file__).resolve().parent.parent / "Joplin" / "temp.md"


@dataclass(frozen=True)
class Tranche:
    index: int
    step_drop_pct: float
    price: float
    amount: float
    shares: int
    spent: float


def _calc_tranches(
    tranche_specs: list[tuple[int, float, float]],
    total_funds: float,
    num_tranches: int,
) -> list[Tranche]:
    """等额分配资金；买不完的余额滚入下一笔可用金额。"""
    per_amount = total_funds / num_tranches
    carry = 0.0
    rows: list[Tranche] = []
    for index, step_drop_pct, price in tranche_specs:
        available = per_amount + carry
        shares = int(available // price)
        spent = shares * price
        carry = available - spent
        rows.append(
            Tranche(
                index=index,
                step_drop_pct=step_drop_pct,
                price=price,
                amount=available,
                shares=shares,
                spent=spent,
            )
        )
    return rows


def calc_mode_a(current_price: float, total_funds: float) -> list[Tranche]:
    """第 1 笔现价买入，之后每笔相对上一笔再跌 16%。"""
    specs: list[tuple[int, float, float]] = [(1, 0.0, current_price)]
    price = current_price
    for i in range(2, TRANCHES_A + 1):
        price = price * 0.84
        specs.append((i, 16.0, price))
    return _calc_tranches(specs, total_funds, TRANCHES_A)


def calc_mode_b(current_price: float, total_funds: float) -> list[Tranche]:
    """每笔相对上一笔（首笔相对现价）再跌 16%。"""
    specs: list[tuple[int, float, float]] = []
    price = current_price
    for i in range(1, TRANCHES + 1):
        price = price * 0.84
        specs.append((i, 16.0, price))
    return _calc_tranches(specs, total_funds, TRANCHES)


COL_SEP = "  |  "


def _styled(text: str, *, bold: bool = False, dim: bool = False) -> str:
    if not sys.stdout.isatty():
        return text
    if bold:
        return f"\033[1m{text}\033[0m"
    if dim:
        return f"\033[2m{text}\033[0m"
    return text


def _cell(value, fmt: str, *, bold: bool = False, dim: bool = False) -> str:
    return _styled(format(value, fmt), bold=bold, dim=dim)


def print_mode(title: str, rows: list[Tranche], total_funds: float) -> None:
    total_spent = sum(r.spent for r in rows)
    total_shares = sum(r.shares for r in rows)
    unused = total_funds - total_spent

    print(title)
    print("-" * 70)
    index_header = _styled(f"{'笔次':>4}", dim=True)
    drop_header = _styled(f"{'跌幅':>3}", dim=True)
    price_header = _styled(f"{'加仓价':>7}", bold=True)
    shares_header = _styled(f"{'股数':>5}", bold=True)
    spent_header = _styled(f"{'实际花费':>6}", dim=True)
    avg_header = _styled(f"{'平均成本':>9}", dim=True)
    header = (
        f"{index_header}  "
        f"{drop_header}"
        f"{COL_SEP}"
        f"{price_header}  "
        f"{shares_header}"
        f"{COL_SEP}"
        f"{spent_header}  "
        f"{avg_header}"
    )
    print(header)
    print("-" * 70)
    cum_spent = 0.0
    cum_shares = 0
    for r in rows:
        cum_spent += r.spent
        cum_shares += r.shares
        avg_cost = cum_spent / cum_shares if cum_shares > 0 else 0.0
        index_cell = _styled(f"{r.index:>4}", dim=True)
        drop_cell = _styled(f"{r.step_drop_pct:>6.0f}%", dim=True)
        price_cell = _styled(f"{r.price:>10.2f}", bold=True)
        shares_cell = _styled(f"{r.shares:>7}", bold=True)
        spent_cell = _styled(f"{r.spent:>10.2f}", dim=True)
        avg_cell = _styled(f"{avg_cost:>12.2f}", dim=True)
        row = (
            f"{index_cell}  "
            f"{drop_cell}"
            f"{COL_SEP}"
            f"{price_cell}  "
            f"{shares_cell}"
            f"{COL_SEP}"
            f"{spent_cell}  "
            f"{avg_cell}"
        )
        print(row)
    print("-" * 70)
    print(
        f"合计: 股数 {total_shares}  |  实际花费 {total_spent:.2f}  |  "
        f"未动用资金 {unused:.2f}"
    )
    print()


def _format_amount(value: float) -> str:
    return f"{value:g}"


def _format_money(value: float) -> str:
    return f"{value:,.2f}"


def _tranche_progress_line(row: Tranche, *, first_at_market: bool) -> str:
    if first_at_market and row.index == 1:
        price_desc = f"现价 {row.price:.2f}"
    else:
        price_desc = f"跌至 {row.price:.2f}（-16%）"
    return (
        f"- [ ] **第 {row.index} 笔** — {price_desc}· "
        f"{row.shares} 股 · 花费 {_format_money(row.spent)}"
    )


def format_md(
    rows: list[Tranche],
    *,
    mode: str,
    current_price: float,
    total_funds: float,
    title: str = "加仓计划",
) -> str:
    per_amount = total_funds / (TRANCHES_A if mode == "A" else TRANCHES)
    total_spent = sum(r.spent for r in rows)
    total_shares = sum(r.shares for r in rows)
    unused = total_funds - total_spent

    if mode == "A":
        mode_desc = "分 6 笔等额加仓，第 1 笔现价买入，之后每笔相对上一笔再跌 16%"
    else:
        mode_desc = "每笔相对上一笔再跌 16%"

    lines = [
        f"# {title}",
        "",
        "## 概览",
        "",
        f"- 当前价格：**{current_price:.2f}**",
        (
            f"- 加仓总资金：{_format_money(total_funds)}"
            f"（每笔分配 {_format_money(per_amount)}）"
        ),
        f"- 模式 **{mode}**：{mode_desc}",
        "",
        "### 建仓进度",
        "",
    ]
    first_at_market = mode == "A"
    lines.extend(
        _tranche_progress_line(row, first_at_market=first_at_market) for row in rows
    )
    lines.extend(
        [
            "",
            "## 合计",
            "",
            "| 项目 | 数值 |",
            "|------|------|",
            f"| 总股数 | **{total_shares:,}** |",
            f"| 实际花费 | **{_format_money(total_spent)}** |",
            f"| 未动用资金 | {_format_money(unused)} |",
            "",
        ]
    )
    return "\n".join(lines)


def export_md(
    current_price: float,
    total_funds: float,
    mode: str,
    *,
    output: Path = DEFAULT_MD_PATH,
    title: str = "加仓计划",
) -> Path:
    if current_price <= 0:
        raise ValueError("当前价格必须大于 0")
    if total_funds <= 0:
        raise ValueError("加仓资金必须大于 0")

    mode = mode.upper()
    if mode == "A":
        rows = calc_mode_a(current_price, total_funds)
    elif mode == "B":
        rows = calc_mode_b(current_price, total_funds)
    else:
        raise ValueError(f"未知模式: {mode}")

    content = format_md(
        rows,
        mode=mode,
        current_price=current_price,
        total_funds=total_funds,
        title=title,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    return output


def print_tg(current_price: float, total_funds: float) -> None:
    if current_price <= 0:
        raise ValueError("当前价格必须大于 0")
    if total_funds <= 0:
        raise ValueError("加仓资金必须大于 0")

    print(f"加仓：现价 {current_price:.2f}，资金 {_format_amount(total_funds)}")
    print()
    print("方案A 现价先买")
    for row in calc_mode_a(current_price, total_funds):
        print(f"{row.price:.2f} @ {row.shares}股")
    print()
    print("方案B 跌 16% 开始接")
    for row in calc_mode_b(current_price, total_funds):
        print(f"{row.price:.2f} @ {row.shares}股")


def run(current_price: float, total_funds: float) -> None:
    if current_price <= 0:
        raise ValueError("当前价格必须大于 0")
    if total_funds <= 0:
        raise ValueError("加仓资金必须大于 0")

    per_amount = total_funds / TRANCHES
    print()
    print(f"当前价格: {current_price:.2f}")
    print(f"加仓总资金: {total_funds:.2f}  (每笔分配 {per_amount:.2f})")
    print()

    mode_a = calc_mode_a(current_price, total_funds)
    mode_b = calc_mode_b(current_price, total_funds)

    print_mode(
        "模式 A：分 6 笔等额加仓，第 1 笔现价买入，之后每笔相对上一笔再跌 16%",
        mode_a,
        total_funds,
    )
    print_mode(
        "模式 B：每笔相对上一笔再跌 16%",
        mode_b,
        total_funds,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="计算 5 笔等额加仓的点位与股数（模式 A / 模式 B）",
    )
    parser.add_argument("-p", "--price", type=float, help="当前标的价格")
    parser.add_argument("-f", "--funds", type=float, help="用于加仓的总资金")
    parser.add_argument(
        "--tg",
        "--telegram",
        action="store_true",
        help="只输出适合 Telegram 转发的下单价和股数",
    )
    parser.add_argument(
        "-mode",
        "--mode",
        choices=["A", "B", "a", "b"],
        type=str,
        help="导出指定模式的 Markdown 到 Joplin/temp.md",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_MD_PATH,
        help=f"Markdown 输出路径（默认: {DEFAULT_MD_PATH}）",
    )
    parser.add_argument(
        "-n",
        "--name",
        default="加仓计划",
        help="Markdown 标题中的标的名称（默认: 加仓计划）",
    )
    return parser.parse_args()


def prompt_float(label: str) -> float:
    while True:
        raw = input(f"{label}: ").strip()
        try:
            value = float(raw)
        except ValueError:
            print("请输入有效数字")
            continue
        if value <= 0:
            print("必须大于 0")
            continue
        return value


def main() -> None:
    args = parse_args()
    if args.mode is not None:
        if args.price is None or args.funds is None:
            print("导出 Markdown 需要同时指定 -p 和 -f", file=sys.stderr)
            sys.exit(1)
        title = (
            f"{args.name} 加仓计划"
            if not args.name.endswith("加仓计划")
            else args.name
        )
        path = export_md(
            args.price,
            args.funds,
            args.mode,
            output=args.output,
            title=title,
        )
        print(f"已导出模式 {args.mode.upper()} → {path}")
        return

    if args.price is not None and args.funds is not None:
        if args.tg:
            print_tg(args.price, args.funds)
        else:
            run(args.price, args.funds)
        return

    print("加仓计算（资金均分 5 笔）")
    price = args.price if args.price is not None else prompt_float("当前标的价格")
    funds = args.funds if args.funds is not None else prompt_float("用于加仓的资金")
    if args.tg:
        print_tg(price, funds)
    else:
        run(price, funds)


if __name__ == "__main__":
    main()
