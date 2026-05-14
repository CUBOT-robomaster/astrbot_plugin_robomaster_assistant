from __future__ import annotations

import html
from typing import Any


def render_html(payload: dict[str, Any]) -> str:
    body = render_flowchart(payload) if payload.get("kind") == "flowchart" else render_table(payload)
    notes = "".join(f"<div class='note'>{escape(note)}</div>" for note in payload.get("notes") or [])
    subtitle = payload.get("subtitle") or ""
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>{CSS}</style>
</head>
<body>
  <section class="rm-card">
    <header class="hero">
      <div>
        <div class="brand">RM Schedule</div>
        <h1>{escape(payload.get("title") or "RoboMaster 赛事查询")}</h1>
        <p>{escape(subtitle)}</p>
      </div>
      <div class="badge">RoboMaster</div>
    </header>
    {body}
    {notes}
  </section>
</body>
</html>"""


def render_table(payload: dict[str, Any]) -> str:
    headers = "".join(f"<th>{escape(column)}</th>" for column in payload.get("columns") or [])
    rows = []
    for row in payload.get("rows") or []:
        cells = "".join(f"<td>{cell_html(cell)}</td>" for cell in row)
        rows.append(f"<tr>{cells}</tr>")
    return f"<table class='match-table'><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def render_flowchart(payload: dict[str, Any]) -> str:
    nodes = payload.get("nodes") or []
    if not nodes:
        rows = payload.get("rows") or []
        nodes = [
            {
                "title": row[0] if len(row) > 0 else f"节点 {index}",
                "subtitle": row[1] if len(row) > 1 else "",
                "red": row[2] if len(row) > 2 else "",
                "blue": row[3] if len(row) > 3 else "",
                "score": row[4] if len(row) > 4 else "",
            }
            for index, row in enumerate(rows, start=1)
        ]
    cards = []
    for node in nodes:
        cards.append(
            "<div class='flow-node'>"
            f"<div class='node-title'>{escape(node.get('title') or '')}</div>"
            f"<div class='node-subtitle'>{escape(node.get('subtitle') or '')}</div>"
            "<div class='versus'>"
            f"<span class='side red'>{escape(node.get('red') or '')}</span>"
            f"<strong>{escape(node.get('score') or 'vs')}</strong>"
            f"<span class='side blue'>{escape(node.get('blue') or '')}</span>"
            "</div>"
            "</div>"
        )
    return f"<div class='flowchart'>{''.join(cards)}</div>"


def escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def cell_html(value: str) -> str:
    text = escape(value)
    if "直播" in value or "待确认" in value:
        return f"<span class='live'>{text}</span>"
    if "已结束" in value:
        return f"<span class='done'>{text}</span>"
    return text


CSS = """
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 24px;
  width: 1280px;
  background: #eef2f7;
  font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
  color: #182033;
}
.rm-card {
  width: 1232px;
  overflow: hidden;
  border-radius: 18px;
  background: #f9fbff;
  border: 1px solid rgba(30, 52, 88, .12);
  box-shadow: 0 20px 52px rgba(15, 31, 56, .18);
}
.hero {
  min-height: 138px;
  padding: 28px 34px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #fff;
  background:
    linear-gradient(110deg, rgba(199, 33, 54, .95), rgba(37, 77, 141, .96)),
    radial-gradient(circle at 82% 20%, rgba(255,255,255,.22), transparent 34%);
}
.brand {
  text-transform: uppercase;
  font-size: 18px;
  font-weight: 800;
  opacity: .86;
}
h1 {
  margin: 8px 0 0;
  font-size: 40px;
  line-height: 1.15;
  letter-spacing: 0;
}
p {
  margin: 10px 0 0;
  font-size: 20px;
  opacity: .88;
}
.badge {
  padding: 12px 18px;
  border: 1px solid rgba(255,255,255,.55);
  border-radius: 999px;
  font-size: 18px;
  font-weight: 700;
}
.match-table {
  width: calc(100% - 40px);
  margin: 20px;
  border-collapse: separate;
  border-spacing: 0;
  table-layout: fixed;
  overflow: hidden;
  border-radius: 12px;
  border: 1px solid #d7e0ed;
}
th {
  padding: 14px 12px;
  background: #25334d;
  color: #fff;
  font-size: 18px;
  text-align: left;
}
td {
  padding: 14px 12px;
  border-top: 1px solid #e1e7f0;
  background: #fff;
  font-size: 17px;
  line-height: 1.35;
  word-break: break-word;
}
tr:nth-child(even) td { background: #f3f6fb; }
td:nth-child(4) { color: #bd1f35; font-weight: 700; }
td:nth-child(5) { color: #1c61ad; font-weight: 700; }
.live {
  color: #d3223f;
  font-weight: 800;
}
.done {
  color: #667085;
}
.flowchart {
  margin: 24px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px 34px;
}
.flow-node {
  position: relative;
  padding: 18px;
  min-height: 154px;
  border-radius: 14px;
  background: #fff;
  border: 1px solid #d7e0ed;
  box-shadow: 0 10px 24px rgba(20, 38, 66, .09);
}
.flow-node::after {
  content: "";
  position: absolute;
  right: -25px;
  top: 50%;
  width: 20px;
  height: 2px;
  background: #aab8cc;
}
.flow-node:nth-child(2n)::after { display: none; }
.node-title {
  font-size: 22px;
  font-weight: 800;
  color: #25334d;
}
.node-subtitle {
  margin-top: 5px;
  font-size: 15px;
  color: #667085;
}
.versus {
  margin-top: 18px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 12px;
  align-items: center;
}
.versus strong {
  font-size: 22px;
  color: #101828;
}
.side {
  min-height: 44px;
  padding: 11px 12px;
  border-radius: 8px;
  color: #fff;
  font-size: 16px;
  font-weight: 700;
  text-align: center;
  word-break: break-word;
}
.side.red { background: linear-gradient(135deg, #ce263e, #8e1b2d); }
.side.blue { background: linear-gradient(135deg, #2467b2, #173d7a); }
.note {
  margin: 0 24px 20px;
  color: #667085;
  font-size: 15px;
}
"""
