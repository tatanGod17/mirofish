"""
MinkSoft PDF Report Generator
Generates a corporate-quality HTML report (print-to-PDF) from a MiroFish simulation report.
"""

from __future__ import annotations

import base64
import json
import os
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

# ─── Logo ────────────────────────────────────────────────────────────────────

_STATIC_DIR = os.path.join(os.path.dirname(__file__), '..', 'static')
_LOGO_PATH = os.path.join(_STATIC_DIR, 'minksoft_logo.png')


def _logo_b64() -> Optional[str]:
    """Return base64-encoded logo or None if not found."""
    if os.path.exists(_LOGO_PATH):
        with open(_LOGO_PATH, 'rb') as f:
            return base64.b64encode(f.read()).decode()
    return None


# ─── Agent log parsing ───────────────────────────────────────────────────────

def _parse_agent_log(report_folder: str) -> Dict[str, Any]:
    """Extract statistics from agent_log.jsonl for charts."""
    log_path = os.path.join(report_folder, 'agent_log.jsonl')
    if not os.path.exists(log_path):
        return {}

    events = []
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass

    sections: Dict[int, Dict] = {}
    tool_counts: Dict[str, int] = defaultdict(int)
    facts_per_section: Dict[int, int] = defaultdict(int)
    total_facts = 0
    start_ts: Optional[float] = None
    end_ts: Optional[float] = None

    for ev in events:
        elapsed = ev.get('elapsed_seconds', 0) or 0
        action = ev.get('action', '')
        idx = ev.get('section_index')
        details = ev.get('details', {}) or {}

        if action == 'report_start':
            start_ts = elapsed
        if action == 'report_complete':
            end_ts = elapsed

        if action == 'section_start' and idx is not None:
            sections.setdefault(idx, {})['title'] = ev.get('section_title', f'Section {idx}')
            sections[idx]['start'] = elapsed

        if action == 'section_complete' and idx is not None:
            sections.setdefault(idx, {})['end'] = elapsed
            sections.setdefault(idx, {})['title'] = ev.get('section_title', f'Section {idx}')

        if action == 'tool_call':
            tool_name = details.get('tool_name') or details.get('name', 'unknown')
            tool_counts[tool_name] += 1

        if action == 'tool_result' and idx is not None:
            count = details.get('facts_count') or details.get('count', 0) or 0
            if isinstance(count, (int, float)):
                facts_per_section[idx] += int(count)
                total_facts += int(count)

    # Compute section durations
    section_durations = {}
    for i, s in sections.items():
        duration = round((s.get('end', 0) - s.get('start', 0)) / 60, 1)
        section_durations[i] = {'title': s.get('title', f'Section {i}'), 'minutes': max(duration, 0.1)}

    total_minutes = round((end_ts or 0) / 60, 1) if end_ts else None

    return {
        'sections': section_durations,
        'tool_counts': dict(tool_counts),
        'facts_per_section': dict(facts_per_section),
        'total_facts': total_facts,
        'total_minutes': total_minutes,
    }


# ─── SVG chart generators ────────────────────────────────────────────────────

def _bar_chart_svg(values: List[float], labels: List[str],
                   title: str, color: str = '#6EE7B7',
                   width: int = 500, height: int = 220) -> str:
    if not values:
        return ''
    max_val = max(values) or 1
    bar_w = max(20, (width - 80) // len(values) - 10)
    x_start = 60
    chart_h = height - 60
    bars_svg = ''
    label_svg = ''
    axis_svg = ''

    # Y-axis gridlines
    for i in range(5):
        y = 20 + chart_h - (i / 4) * chart_h
        val = round((i / 4) * max_val, 1)
        axis_svg += f'<line x1="{x_start}" y1="{y:.0f}" x2="{width-10}" y2="{y:.0f}" stroke="#e2e8f0" stroke-width="1"/>'
        axis_svg += f'<text x="{x_start-5}" y="{y+4:.0f}" text-anchor="end" fill="#94a3b8" font-size="9">{val}</text>'

    for i, (v, lbl) in enumerate(zip(values, labels)):
        x = x_start + i * (bar_w + 10) + 5
        bar_h = max(2, int((v / max_val) * chart_h))
        y = 20 + chart_h - bar_h
        bars_svg += (
            f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bar_h}" '
            f'rx="3" fill="{color}" opacity="0.85"/>'
            f'<text x="{x + bar_w//2}" y="{y - 4}" text-anchor="middle" '
            f'fill="#374151" font-size="9" font-weight="600">{v}</text>'
        )
        short = lbl[:12] + ('…' if len(lbl) > 12 else '')
        label_svg += (
            f'<text x="{x + bar_w//2}" y="{20 + chart_h + 14}" '
            f'text-anchor="middle" fill="#64748b" font-size="8">{short}</text>'
        )

    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;max-width:{width}px">'
        f'<text x="{width//2}" y="12" text-anchor="middle" fill="#1e3a5f" '
        f'font-size="11" font-weight="700">{title}</text>'
        f'{axis_svg}{bars_svg}{label_svg}'
        f'<line x1="{x_start}" y1="20" x2="{x_start}" y2="{20+chart_h}" stroke="#cbd5e1" stroke-width="1.5"/>'
        f'<line x1="{x_start}" y1="{20+chart_h}" x2="{width-10}" y2="{20+chart_h}" stroke="#cbd5e1" stroke-width="1.5"/>'
        f'</svg>'
    )


def _pie_chart_svg(values: List[float], labels: List[str],
                   title: str, width: int = 400, height: int = 220) -> str:
    if not values or sum(values) == 0:
        return ''
    colors = ['#6EE7B7', '#3B82F6', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#14B8A6']
    total = sum(values)
    cx, cy, r = width // 2 - 40, height // 2 + 10, min(height, width) // 2 - 30
    paths = ''
    legend = ''
    angle = -90.0

    for i, (v, lbl) in enumerate(zip(values, labels)):
        pct = v / total
        sweep = pct * 360
        a1 = angle * (3.14159265 / 180)
        a2 = (angle + sweep) * (3.14159265 / 180)
        x1, y1 = cx + r * (a1.__class__.__import__ if False else __builtins__['__import__']('math').cos(a1)), \
                  cy + r * __builtins__['__import__']('math').sin(a1)
        x2, y2 = cx + r * __builtins__['__import__']('math').cos(a2), \
                  cy + r * __builtins__['__import__']('math').sin(a2)
        large = 1 if sweep > 180 else 0
        col = colors[i % len(colors)]
        paths += (
            f'<path d="M {cx} {cy} L {x1:.1f} {y1:.1f} '
            f'A {r} {r} 0 {large} 1 {x2:.1f} {y2:.1f} Z" '
            f'fill="{col}" stroke="white" stroke-width="1.5"/>'
        )
        ly = 35 + i * 16
        pct_str = f'{pct*100:.0f}%'
        short = lbl[:14] + ('…' if len(lbl) > 14 else '')
        legend += (
            f'<rect x="{width-75}" y="{ly-8}" width="10" height="10" rx="2" fill="{col}"/>'
            f'<text x="{width-62}" y="{ly}" fill="#374151" font-size="9">{short} {pct_str}</text>'
        )
        angle += sweep

    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;max-width:{width}px">'
        f'<text x="{width//2 - 40}" y="14" text-anchor="middle" fill="#1e3a5f" '
        f'font-size="11" font-weight="700">{title}</text>'
        f'{paths}{legend}'
        f'</svg>'
    )


def _timeline_svg(sections: Dict[int, Dict], width: int = 640, height: int = 160) -> str:
    if not sections:
        return ''
    items = sorted(sections.items())
    max_min = max((s['minutes'] for _, s in items), default=1)
    bar_h = 22
    pad = 10
    label_w = 160
    chart_w = width - label_w - 20
    colors = ['#6EE7B7', '#3B82F6', '#F59E0B', '#8B5CF6']
    bars = ''
    for row, (idx, s) in enumerate(items):
        y = pad + row * (bar_h + 8)
        bw = max(4, int((s['minutes'] / max_min) * chart_w))
        col = colors[row % len(colors)]
        short = s['title'][:22] + ('…' if len(s['title']) > 22 else '')
        bars += (
            f'<text x="{label_w - 5}" y="{y + bar_h//2 + 4}" text-anchor="end" '
            f'fill="#374151" font-size="9">{short}</text>'
            f'<rect x="{label_w}" y="{y}" width="{bw}" height="{bar_h}" rx="4" fill="{col}" opacity="0.85"/>'
            f'<text x="{label_w + bw + 4}" y="{y + bar_h//2 + 4}" '
            f'fill="#64748b" font-size="9">{s["minutes"]}m</text>'
        )
    actual_h = pad * 2 + len(items) * (bar_h + 8)
    return (
        f'<svg viewBox="0 0 {width} {actual_h}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;max-width:{width}px">'
        f'{bars}'
        f'</svg>'
    )


# ─── Markdown → HTML (minimal, no deps) ──────────────────────────────────────

def _md_to_html(md: str) -> str:
    """Very lightweight Markdown → HTML converter."""
    # Try to use markdown lib if available
    try:
        import markdown as _md
        return _md.markdown(md, extensions=['extra', 'nl2br'])
    except ImportError:
        pass

    html = md
    # Headers
    html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)
    # Bold / italic
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
    # Blockquote
    html = re.sub(r'^> (.+)$', r'<blockquote>\1</blockquote>', html, flags=re.MULTILINE)
    # HR
    html = re.sub(r'^---+$', r'<hr>', html, flags=re.MULTILINE)
    # Bullet lists
    def _list_block(m):
        items = re.findall(r'^[-*] (.+)$', m.group(0), flags=re.MULTILINE)
        return '<ul>' + ''.join(f'<li>{i}</li>' for i in items) + '</ul>'
    html = re.sub(r'(^[-*] .+$\n?)+', _list_block, html, flags=re.MULTILINE)
    # Paragraphs
    lines = html.split('\n')
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith('<'):
            result.append(f'<p>{stripped}</p>')
        else:
            result.append(line)
    return '\n'.join(result)


# ─── UI label translations ────────────────────────────────────────────────────

_UI_LABELS: Dict[str, Dict[str, str]] = {
    'en': {
        'badge':             'Simulation Analysis Report',
        'cover_label':       'MiroFish · AI Swarm Intelligence',
        'objective':         'Objective',
        'powered':           'Powered by MinkSoft',
        'sections':          'Sections',
        'facts_found':       'Facts Found',
        'ai_tool_calls':     'AI Tool Calls',
        'gen_time':          'Generation Time',
        'exec_dashboard':    'Executive Dashboard',
        'report_overview':   'Report Overview',
        'report_sections_lbl': 'Report Sections',
        'key_facts_lbl':     'Key Facts Extracted',
        'minutes_lbl':       'Minutes to Generate',
        'chart_facts':       'Key Facts per Section',
        'chart_tools':       'AI Tool Usage',
        'chart_timeline':    'Section Generation Timeline',
        'no_tool_data':      'No tool data',
        'no_timeline_data':  'No timeline data',
        'ai_tools_used':     'AI Tools Used',
        'no_tool_recorded':  'No tool usage recorded.',
        'full_report':       'Full Report',
        'footer_sim':        'MiroFish Simulation Analysis',
        'no_content':        'No content generated.',
        'min':               'min',
        'facts':             'facts',
        'tool_descs': {
            'insight_forge':    'Multi-step semantic search with sub-queries',
            'panorama_search':  'Broad graph traversal & entity linking',
            'quick_search':     'Fast keyword & vector lookup',
            'interview_agents': 'Direct interview of simulated agents',
        },
        'tool_names': {
            'insight_forge':    'Deep Insight',
            'panorama_search':  'Panorama Search',
            'quick_search':     'Quick Search',
            'interview_agents': 'Agent Interview',
        },
    },
    'es': {
        'badge':             'Informe de Análisis de Simulación',
        'cover_label':       'MiroFish · Inteligencia de Enjambre IA',
        'objective':         'Objetivo',
        'powered':           'Desarrollado por MinkSoft',
        'sections':          'Secciones',
        'facts_found':       'Hechos Encontrados',
        'ai_tool_calls':     'Llamadas a IA',
        'gen_time':          'Tiempo de Generación',
        'exec_dashboard':    'Panel Ejecutivo',
        'report_overview':   'Resumen del Informe',
        'report_sections_lbl': 'Secciones del Informe',
        'key_facts_lbl':     'Hechos Clave Extraídos',
        'minutes_lbl':       'Minutos de Generación',
        'chart_facts':       'Hechos Clave por Sección',
        'chart_tools':       'Uso de Herramientas IA',
        'chart_timeline':    'Línea de Tiempo de Generación',
        'no_tool_data':      'Sin datos de herramientas',
        'no_timeline_data':  'Sin datos de tiempo',
        'ai_tools_used':     'Herramientas IA Utilizadas',
        'no_tool_recorded':  'No se registró uso de herramientas.',
        'full_report':       'Informe Completo',
        'footer_sim':        'Análisis de Simulación MiroFish',
        'no_content':        'Sin contenido generado.',
        'min':               'min',
        'facts':             'hechos',
        'tool_descs': {
            'insight_forge':    'Búsqueda semántica profunda con subconsultas',
            'panorama_search':  'Traversal amplio del grafo y vinculación de entidades',
            'quick_search':     'Búsqueda rápida por palabras clave y vectores',
            'interview_agents': 'Entrevista directa a agentes simulados',
        },
        'tool_names': {
            'insight_forge':    'Insight Profundo',
            'panorama_search':  'Búsqueda Panorámica',
            'quick_search':     'Búsqueda Rápida',
            'interview_agents': 'Entrevista de Agentes',
        },
    },
    'zh': {
        'badge':             '仿真分析报告',
        'cover_label':       'MiroFish · AI 群体智能',
        'objective':         '目标',
        'powered':           '由 MinkSoft 驱动',
        'sections':          '章节数',
        'facts_found':       '发现事实',
        'ai_tool_calls':     'AI 工具调用',
        'gen_time':          '生成时间',
        'exec_dashboard':    '执行仪表板',
        'report_overview':   '报告概览',
        'report_sections_lbl': '报告章节',
        'key_facts_lbl':     '提取关键事实',
        'minutes_lbl':       '生成分钟数',
        'chart_facts':       '各章节关键事实数',
        'chart_tools':       'AI 工具使用情况',
        'chart_timeline':    '章节生成时间轴',
        'no_tool_data':      '无工具数据',
        'no_timeline_data':  '无时间轴数据',
        'ai_tools_used':     '已使用的 AI 工具',
        'no_tool_recorded':  '未记录工具使用情况。',
        'full_report':       '完整报告',
        'footer_sim':        'MiroFish 仿真分析',
        'no_content':        '未生成内容。',
        'min':               '分钟',
        'facts':             '事实',
        'tool_descs': {
            'insight_forge':    '带子查询的多步语义搜索',
            'panorama_search':  '宽泛图谱遍历与实体链接',
            'quick_search':     '快速关键词与向量检索',
            'interview_agents': '直接访谈模拟智能体',
        },
        'tool_names': {
            'insight_forge':    '深度洞察',
            'panorama_search':  '全景搜索',
            'quick_search':     '快速搜索',
            'interview_agents': '智能体访谈',
        },
    },
}


# ─── Main generator ──────────────────────────────────────────────────────────

def generate_pdf_report(report_folder: str, report: Any, locale: str = 'en') -> str:
    """
    Generate a corporate HTML report suitable for printing to PDF.
    Returns the HTML string.
    """
    import math  # noqa: F401 – used in pie chart (safe here)

    lbl = _UI_LABELS.get(locale, _UI_LABELS['en'])

    stats = _parse_agent_log(report_folder)
    logo_b64 = _logo_b64()
    logo_tag = (
        f'<img src="data:image/png;base64,{logo_b64}" alt="MinkSoft" class="logo"/>'
        if logo_b64 else
        '<div class="logo-text">MinkSoft</div>'
    )

    outline = report.outline
    sections_data = outline.sections if outline else []
    report_title = outline.title if outline else 'Simulation Analysis Report'
    report_summary = outline.summary if outline else ''
    sim_req = getattr(report, 'simulation_requirement', '')
    created_at = getattr(report, 'created_at', '')[:10] or datetime.now().strftime('%Y-%m-%d')
    total_sections = len(sections_data)
    total_facts = stats.get('total_facts', 0)
    total_minutes = stats.get('total_minutes') or '—'
    tool_counts = stats.get('tool_counts', {})
    section_durations = stats.get('sections', {})
    facts_per_section = stats.get('facts_per_section', {})

    # ── Charts ────────────────────────────────────────────────────────────────
    # Facts per section bar chart
    if section_durations:
        bar_labels = [v['title'] for k, v in sorted(section_durations.items())]
        bar_values = [facts_per_section.get(k, 0) for k in sorted(section_durations.keys())]
        facts_bar = _bar_chart_svg(bar_values, bar_labels, lbl['chart_facts'], '#6EE7B7')
    else:
        facts_bar = ''

    # Tool usage pie chart
    if tool_counts:
        tool_names = lbl['tool_names']
        pie_labels = [tool_names.get(k, k) for k in tool_counts]
        pie_values = list(tool_counts.values())
        tools_pie = _pie_chart_svg_safe(pie_values, pie_labels, lbl['chart_tools'])
    else:
        tools_pie = ''

    # Section duration timeline
    timeline = _timeline_svg(section_durations, width=560) if section_durations else ''

    # ── Section content ───────────────────────────────────────────────────────
    sections_html = ''
    for loop_idx, sec in enumerate(sections_data, start=1):
        sec_title = sec.title if hasattr(sec, 'title') else str(sec)
        # Try to read the section markdown file (1-based index, zero-padded)
        sec_file = os.path.join(report_folder, f'section_{loop_idx:02d}.md')
        if os.path.exists(sec_file):
            with open(sec_file, 'r', encoding='utf-8') as f:
                sec_md = f.read()
        else:
            sec_md = sec.content if hasattr(sec, 'content') else ''

        sec_content_html = _md_to_html(sec_md) if sec_md else f'<p><em>{lbl["no_content"]}</em></p>'
        duration_str = ''
        if loop_idx in section_durations:
            duration_str = f'<span class="sec-meta">{section_durations[loop_idx]["minutes"]} {lbl["min"]}</span>'
        facts_str = ''
        if loop_idx in facts_per_section and facts_per_section[loop_idx] > 0:
            facts_str = f'<span class="sec-meta">{facts_per_section[loop_idx]} {lbl["facts"]}</span>'

        sections_html += f'''
        <div class="section-page">
          <div class="section-header">
            <span class="section-num">{loop_idx:02d}</span>
            <div>
              <div class="section-title">{sec_title}</div>
              <div class="section-badges">{duration_str}{facts_str}</div>
            </div>
          </div>
          <div class="section-body">{sec_content_html}</div>
        </div>
        '''

    # If no structured sections, fall back to full markdown
    if not sections_html and report.markdown_content:
        sections_html = f'<div class="section-page"><div class="section-body">{_md_to_html(report.markdown_content)}</div></div>'

    # ── Tool cards ────────────────────────────────────────────────────────────
    tool_colors = {
        'insight_forge': '#6EE7B7',
        'panorama_search': '#3B82F6',
        'quick_search': '#F59E0B',
        'interview_agents': '#8B5CF6',
    }
    tool_cards_html = ''
    for k, count in sorted(tool_counts.items(), key=lambda x: -x[1]):
        name = lbl['tool_names'].get(k, k)
        desc = lbl['tool_descs'].get(k, '')
        color = tool_colors.get(k, '#94a3b8')
        tool_cards_html += f'''
        <div class="tool-card">
          <div class="tool-dot" style="background:{color}"></div>
          <div><div class="tool-name">{name}</div><div class="tool-desc">{desc}</div></div>
          <div class="tool-count" style="color:{color}">{count}</div>
        </div>'''

    # ── HTML assembly ─────────────────────────────────────────────────────────
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{report_title} — MinkSoft</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;800&display=swap');
  body {{
    font-family: Inter, 'Segoe UI', Arial, sans-serif;
    font-size: 12px;
    line-height: 1.65;
    color: #1a202c;
    background: #fff;
  }}

  /* ── Cover ── */
  .cover {{
    background: linear-gradient(135deg, #0b0f1a 0%, #1a2744 55%, #0d2235 100%);
    color: white;
    min-height: 100vh;
    padding: 60px 70px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    page-break-after: always;
  }}
  .cover-top {{ display: flex; justify-content: space-between; align-items: flex-start; }}
  .logo {{ height: 52px; opacity: 0.95; }}
  .logo-text {{ font-size: 22px; font-weight: 800; color: #6EE7B7; letter-spacing: -0.5px; }}
  .cover-badge {{
    background: rgba(110,231,183,0.15); border: 1px solid rgba(110,231,183,0.4);
    color: #6EE7B7; padding: 5px 14px; border-radius: 20px;
    font-size: 10px; font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase;
  }}
  .cover-body {{ padding: 60px 0 40px; }}
  .cover-label {{ color: #6EE7B7; font-size: 11px; font-weight: 700; letter-spacing: 2px; text-transform: uppercase; margin-bottom: 14px; }}
  .cover-title {{ font-size: 34px; font-weight: 800; line-height: 1.2; letter-spacing: -0.5px; margin-bottom: 20px; }}
  .cover-summary {{ color: #94a3b8; font-size: 13px; max-width: 580px; line-height: 1.7; margin-bottom: 40px; }}
  .cover-meta-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }}
  .cover-meta-card {{
    background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1);
    border-radius: 10px; padding: 16px; text-align: center;
  }}
  .cover-meta-value {{ font-size: 28px; font-weight: 800; color: #6EE7B7; }}
  .cover-meta-label {{ font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: 1px; margin-top: 4px; }}
  .cover-bottom {{ display: flex; justify-content: space-between; align-items: flex-end; color: #475569; font-size: 10px; }}
  .cover-bottom .req {{ max-width: 60%; color: #64748b; font-style: italic; }}

  /* ── Page layout ── */
  .page {{
    padding: 50px 70px;
    max-width: 900px;
    margin: 0 auto;
  }}
  .page-break {{ page-break-before: always; }}

  /* ── Section headers ── */
  .page-title {{
    font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 2px;
    color: #6EE7B7; margin-bottom: 6px;
  }}
  h2.block-title {{
    font-size: 22px; font-weight: 800; color: #0f172a;
    border-bottom: 2px solid #e2e8f0; padding-bottom: 10px; margin-bottom: 20px;
  }}

  /* ── Dashboard cards ── */
  .dashboard-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 30px; }}
  .dash-card {{
    background: linear-gradient(135deg, #f8fafc, #f1f5f9);
    border: 1px solid #e2e8f0; border-radius: 12px; padding: 18px 14px; text-align: center;
  }}
  .dash-value {{ font-size: 30px; font-weight: 800; color: #0f172a; }}
  .dash-label {{ font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: 1px; margin-top: 4px; }}
  .dash-icon {{ font-size: 18px; margin-bottom: 6px; }}

  /* ── Charts ── */
  .charts-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 28px; }}
  .chart-card {{
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 20px;
  }}
  .chart-card.full {{ grid-column: 1 / -1; }}
  .chart-title {{ font-size: 11px; font-weight: 700; color: #1e3a5f; margin-bottom: 14px; }}

  /* ── Tool cards ── */
  .tools-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 14px; }}
  .tool-card {{
    display: flex; align-items: center; gap: 10px;
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 14px;
  }}
  .tool-dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
  .tool-name {{ font-weight: 700; font-size: 11px; color: #0f172a; }}
  .tool-desc {{ font-size: 10px; color: #64748b; }}
  .tool-count {{ font-size: 20px; font-weight: 800; margin-left: auto; }}

  /* ── Report sections ── */
  .section-page {{ margin-bottom: 40px; page-break-inside: avoid; }}
  .section-header {{
    display: flex; align-items: flex-start; gap: 14px;
    background: linear-gradient(90deg, #f0fdf4, #f8fafc);
    border-left: 4px solid #6EE7B7; border-radius: 0 10px 10px 0;
    padding: 14px 18px; margin-bottom: 16px;
  }}
  .section-num {{
    background: #0f172a; color: #6EE7B7;
    width: 32px; height: 32px; border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-size: 13px; font-weight: 800; flex-shrink: 0;
    font-family: monospace;
  }}
  .section-title {{ font-size: 16px; font-weight: 700; color: #0f172a; }}
  .section-badges {{ display: flex; gap: 8px; margin-top: 4px; }}
  .sec-meta {{
    background: #e0f2fe; color: #0369a1;
    font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 4px;
  }}
  .section-body {{ color: #374151; font-size: 12px; line-height: 1.7; }}
  .section-body h1 {{ font-size: 18px; font-weight: 800; color: #0f172a; margin: 18px 0 8px; }}
  .section-body h2 {{ font-size: 15px; font-weight: 700; color: #1e3a5f; margin: 16px 0 8px; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }}
  .section-body h3 {{ font-size: 13px; font-weight: 700; color: #374151; margin: 12px 0 6px; }}
  .section-body p {{ margin-bottom: 10px; }}
  .section-body ul, .section-body ol {{ padding-left: 20px; margin-bottom: 10px; }}
  .section-body li {{ margin-bottom: 4px; }}
  .section-body blockquote {{
    background: #f0fdf4; border-left: 3px solid #6EE7B7;
    padding: 10px 14px; border-radius: 0 6px 6px 0;
    margin: 12px 0; font-style: italic; color: #374151;
  }}
  .section-body strong {{ color: #0f172a; }}
  .section-body hr {{ border: none; border-top: 1px solid #e2e8f0; margin: 16px 0; }}

  /* ── Footer ── */
  .footer {{
    display: flex; justify-content: space-between; align-items: center;
    border-top: 1px solid #e2e8f0; padding-top: 12px; margin-top: 40px;
    font-size: 9px; color: #94a3b8;
  }}
  .footer-brand {{ display: flex; align-items: center; gap: 6px; font-weight: 700; color: #64748b; }}
  .footer-logo {{ height: 16px; opacity: 0.6; }}

  /* ── Print ── */
  @media print {{
    body {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    .cover {{ min-height: 100vh; }}
    .page-break {{ page-break-before: always; }}
    @page {{ margin: 0; size: A4; }}
  }}
</style>
</head>
<body>

<!-- ═══════════════ COVER ═══════════════ -->
<div class="cover">
  <div class="cover-top">
    {logo_tag}
    <span class="cover-badge">{lbl['badge']}</span>
  </div>

  <div class="cover-body">
    <div class="cover-label">{lbl['cover_label']}</div>
    <div class="cover-title">{report_title}</div>
    <div class="cover-summary">{report_summary}</div>

    <div class="cover-meta-grid">
      <div class="cover-meta-card">
        <div class="cover-meta-value">{total_sections}</div>
        <div class="cover-meta-label">{lbl['sections']}</div>
      </div>
      <div class="cover-meta-card">
        <div class="cover-meta-value">{total_facts}</div>
        <div class="cover-meta-label">{lbl['facts_found']}</div>
      </div>
      <div class="cover-meta-card">
        <div class="cover-meta-value">{sum(tool_counts.values()) if tool_counts else 0}</div>
        <div class="cover-meta-label">{lbl['ai_tool_calls']}</div>
      </div>
      <div class="cover-meta-card">
        <div class="cover-meta-value">{total_minutes}m</div>
        <div class="cover-meta-label">{lbl['gen_time']}</div>
      </div>
    </div>
  </div>

  <div class="cover-bottom">
    <div class="req"><strong>{lbl['objective']}:</strong> {sim_req[:200]}{'...' if len(sim_req) > 200 else ''}</div>
    <div style="text-align:right">
      <div style="color:#6EE7B7;font-weight:700">{lbl['powered']}</div>
      <div style="margin-top:2px">{created_at}</div>
    </div>
  </div>
</div>

<!-- ═══════════════ DASHBOARD ═══════════════ -->
<div class="page page-break">
  <div class="page-title">{lbl['exec_dashboard']}</div>
  <h2 class="block-title">{lbl['report_overview']}</h2>

  <div class="dashboard-grid">
    <div class="dash-card">
      <div class="dash-icon">📄</div>
      <div class="dash-value">{total_sections}</div>
      <div class="dash-label">{lbl['report_sections_lbl']}</div>
    </div>
    <div class="dash-card">
      <div class="dash-icon">🔍</div>
      <div class="dash-value">{total_facts}</div>
      <div class="dash-label">{lbl['key_facts_lbl']}</div>
    </div>
    <div class="dash-card">
      <div class="dash-icon">🤖</div>
      <div class="dash-value">{sum(tool_counts.values()) if tool_counts else 0}</div>
      <div class="dash-label">{lbl['ai_tool_calls']}</div>
    </div>
    <div class="dash-card">
      <div class="dash-icon">⏱</div>
      <div class="dash-value">{total_minutes}</div>
      <div class="dash-label">{lbl['minutes_lbl']}</div>
    </div>
  </div>

  <!-- Charts row -->
  <div class="charts-grid">
    <div class="chart-card">
      <div class="chart-title">{lbl['chart_facts']}</div>
      {facts_bar}
    </div>
    <div class="chart-card">
      <div class="chart-title">{lbl['chart_tools']}</div>
      {tools_pie if tools_pie else f'<p style="color:#94a3b8;font-size:11px">{lbl["no_tool_data"]}</p>'}
    </div>
    <div class="chart-card full">
      <div class="chart-title">{lbl['chart_timeline']}</div>
      {timeline if timeline else f'<p style="color:#94a3b8;font-size:11px">{lbl["no_timeline_data"]}</p>'}
    </div>
  </div>

  <!-- Tool breakdown -->
  <h2 class="block-title" style="margin-top:20px">{lbl['ai_tools_used']}</h2>
  <div class="tools-grid">
    {tool_cards_html if tool_cards_html else f'<p style="color:#94a3b8">{lbl["no_tool_recorded"]}</p>'}
  </div>

  <div class="footer">
    <span>{lbl['footer_sim']} · {created_at}</span>
    <span class="footer-brand">
      {f'<img src="data:image/png;base64,{logo_b64}" class="footer-logo"/>' if logo_b64 else ''}
      {lbl['powered']}
    </span>
  </div>
</div>

<!-- ═══════════════ SECTIONS ═══════════════ -->
<div class="page page-break">
  <div class="page-title">{lbl['full_report']}</div>
  <h2 class="block-title">{report_title}</h2>

  {sections_html}

  <div class="footer">
    <span>{lbl['footer_sim']} · {created_at}</span>
    <span class="footer-brand">
      {f'<img src="data:image/png;base64,{logo_b64}" class="footer-logo"/>' if logo_b64 else ''}
      {lbl['powered']}
    </span>
  </div>
</div>

</body>
</html>'''

    return html


def _pie_chart_svg_safe(values, labels, title, width=380, height=220):
    """Pie chart without __builtins__ trickery."""
    import math
    if not values or sum(values) == 0:
        return ''
    colors = ['#6EE7B7', '#3B82F6', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899']
    total = sum(values)
    cx, cy, r = width // 2 - 40, height // 2 + 10, min(height, width) // 2 - 30
    paths, legend = '', ''
    angle = -90.0
    for i, (v, lbl) in enumerate(zip(values, labels)):
        pct = v / total
        sweep = pct * 360
        a1 = math.radians(angle)
        a2 = math.radians(angle + sweep)
        x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
        x2, y2 = cx + r * math.cos(a2), cy + r * math.sin(a2)
        large = 1 if sweep > 180 else 0
        col = colors[i % len(colors)]
        paths += (
            f'<path d="M {cx} {cy} L {x1:.1f} {y1:.1f} '
            f'A {r} {r} 0 {large} 1 {x2:.1f} {y2:.1f} Z" '
            f'fill="{col}" stroke="white" stroke-width="1.5"/>'
        )
        ly = 30 + i * 16
        pct_str = f'{pct*100:.0f}%'
        short = lbl[:14] + ('…' if len(lbl) > 14 else '')
        legend += (
            f'<rect x="{width-80}" y="{ly-8}" width="10" height="10" rx="2" fill="{col}"/>'
            f'<text x="{width-67}" y="{ly}" fill="#374151" font-size="9">{short} {pct_str}</text>'
        )
        angle += sweep
    return (
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%;max-width:{width}px">'
        f'{paths}{legend}</svg>'
    )


# Remove the broken _pie_chart_svg (it used __builtins__ trick)
_pie_chart_svg = _pie_chart_svg_safe
