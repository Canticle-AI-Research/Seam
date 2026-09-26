"""Skill Knowledge Graph projection and dependency-free HTML renderer."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

from .planner import ActivationPlan
from .registry import RegistrySnapshot


@dataclass(frozen=True)
class SkillGraphNode:
    node_id: str
    kind: str
    label: str
    active: bool = False
    details: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.node_id,
            "kind": self.kind,
            "label": self.label,
            "active": self.active,
            "details": {key: value for key, value in self.details},
        }


@dataclass(frozen=True)
class SkillGraphEdge:
    source: str
    target: str
    kind: str
    declared: bool
    active: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "kind": self.kind,
            "declared": self.declared,
            "active": self.active,
        }


@dataclass(frozen=True)
class SkillGraphPayload:
    nodes: tuple[SkillGraphNode, ...]
    edges: tuple[SkillGraphEdge, ...]
    snapshot_fingerprint: str
    plan_fingerprint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "seam-skill-graph/v1",
            "snapshot_fingerprint": self.snapshot_fingerprint,
            "plan_fingerprint": self.plan_fingerprint,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_skill_graph(
    snapshot: RegistrySnapshot, plan: ActivationPlan | None = None
) -> SkillGraphPayload:
    packages = {package.skill_id: package for package in snapshot.packages}
    if plan is not None:
        if plan.snapshot_fingerprint != snapshot.fingerprint:
            raise ValueError("activation plan snapshot fingerprint mismatch")
        for reference in plan.skills:
            package = packages.get(reference.skill_id)
            if package is None:
                raise ValueError(f"activation plan references missing skill: {reference.skill_id}")
            if package.revision != reference.revision:
                raise ValueError(
                    f"activation plan revision mismatch for {reference.skill_id}: "
                    f"plan {reference.revision}, snapshot {package.revision}"
                )
    active_ids = {skill.skill_id for skill in plan.skills} if plan else set()
    nodes: dict[str, SkillGraphNode] = {}
    edges: set[tuple[str, str, str, bool, bool]] = set()

    def add_facet(kind: str, value: str) -> str:
        node_id = f"{kind}:{value}"
        nodes.setdefault(node_id, SkillGraphNode(node_id, kind, value))
        return node_id

    for package in snapshot.packages:
        skill_node = f"skill:{package.skill_id}"
        nodes[skill_node] = SkillGraphNode(
            skill_node,
            "skill",
            package.title,
            package.skill_id in active_ids,
            (
                ("skill_id", package.skill_id),
                ("revision", package.revision),
                ("summary", package.summary),
                ("summary_provenance", "declared" if package.declared.summary else "derived"),
                ("description", package.description),
                (
                    "description_provenance",
                    "declared" if package.declared.description else "derived",
                ),
                ("title_provenance", "declared" if package.declared.title else "derived"),
                ("source", f"{package.derived.source_label}={package.derived.source_path}"),
            ),
        )
        facets = (
            ("capability", "has_capability", package.declared.capabilities),
            ("context", "has_context", package.declared.contexts),
            ("category", "has_category", (package.declared.category,) if package.declared.category else ()),
            ("tool", "needs_tool", package.declared.tools),
            ("permission", "needs_permission", package.declared.permissions),
        )
        for kind, edge_kind, values in facets:
            for value in values:
                target = add_facet(kind, value)
                edges.add((skill_node, target, edge_kind, True, package.skill_id in active_ids))
        for relation in package.declared.relations:
            target_id = relation.target if ":" in relation.target else f"{package.namespace}:{relation.target}"
            target = f"skill:{target_id}"
            if target not in nodes:
                nodes[target] = SkillGraphNode(
                    target,
                    "skill",
                    target_id,
                    target_id in active_ids,
                    (("skill_id", target_id), ("missing", "true")),
                )
            edges.add(
                (
                    skill_node,
                    target,
                    relation.kind,
                    True,
                    package.skill_id in active_ids and target_id in active_ids,
                )
            )
        _add_source_hierarchy(nodes, edges, package, skill_node, package.skill_id in active_ids)
    graph_edges = tuple(
        SkillGraphEdge(source, target, kind, declared, active)
        for source, target, kind, declared, active in sorted(edges)
    )
    return SkillGraphPayload(
        nodes=tuple(nodes[node_id] for node_id in sorted(nodes)),
        edges=graph_edges,
        snapshot_fingerprint=snapshot.fingerprint,
        plan_fingerprint=plan.fingerprint if plan else None,
    )


_SAFE_SOURCE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _add_source_hierarchy(
    nodes: dict[str, SkillGraphNode],
    edges: set[tuple[str, str, str, bool, bool]],
    package,
    skill_node: str,
    active: bool,
) -> None:
    root_id = f"source-root:{package.derived.source_label}"
    existing_root = nodes.get(root_id)
    nodes[root_id] = SkillGraphNode(
        root_id,
        "source_root",
        package.derived.source_label,
        active or bool(existing_root and existing_root.active),
        (("provenance", "derived-from-source-path"),),
    )
    parent = root_id
    cumulative: list[str] = []
    parent_segments = package.derived.source_path.split("/")[:-1]
    for segment in parent_segments:
        if not _SAFE_SOURCE_SEGMENT.fullmatch(segment) or segment in {".", ".."}:
            continue
        cumulative.append(segment)
        group_id = f"source-group:{package.derived.source_label}:{'/'.join(cumulative)}"
        existing = nodes.get(group_id)
        nodes[group_id] = SkillGraphNode(
            group_id,
            "source_group",
            segment,
            active or bool(existing and existing.active),
            (
                ("path", "/".join(cumulative)),
                ("provenance", "derived-from-source-path"),
            ),
        )
        edges.add((parent, group_id, "contains", False, active))
        parent = group_id
    edges.add((parent, skill_node, "contains_skill", False, active))


def render_skill_graph_html(payload: SkillGraphPayload) -> str:
    """Render a single-file, CSP-friendly graph viewer with escaped payload."""

    safe_json = (
        payload.to_json()
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    node_count = max(1, len(payload.nodes))
    columns = max(1, math.ceil(math.sqrt(node_count * 1.6)))
    rows = math.ceil(node_count / columns)
    graph_width = max(760, 180 + columns * 190)
    graph_height = max(560, 160 + rows * 130)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SEAM Skill Knowledge Graph</title>
<style>
:root {{ color-scheme: dark; font-family: system-ui,sans-serif; background:#0b1020; color:#e9eefb; }}
body {{ margin:0; display:grid; grid-template-columns:minmax(0,1fr) 21rem; grid-template-rows:auto 1fr; min-height:100vh; }}
header {{ grid-column:1/-1; padding:.8rem 1rem; display:flex; gap:.8rem; align-items:center; background:#141b30; }}
input,select,button {{ background:#080d1a; color:inherit; border:1px solid #425070; padding:.5rem; border-radius:.35rem; }}
#canvas {{ min-height:36rem; overflow:hidden; }} svg {{ width:100%; height:calc(100vh - 4rem); min-height:36rem; touch-action:none; }}
aside {{ padding:1rem; border-left:1px solid #29334d; background:#10172a; overflow:auto; }}
.edge {{ stroke:#566482; stroke-width:1.3; }} .edge.active {{ stroke:#ffd166; stroke-width:3; }}
.node circle {{ fill:#263455; stroke:#8094c2; stroke-width:1.5; cursor:pointer; }}
.node.active circle {{ fill:#8a5b12; stroke:#ffd166; stroke-width:3; }}
.node text {{ fill:#f5f7ff; font-size:12px; pointer-events:none; }}
.hidden {{ display:none; }} dt {{ color:#9fb3df; margin-top:.7rem; }} dd {{ margin-left:0; overflow-wrap:anywhere; }}
</style>
</head>
<body>
<header><strong>Skill Knowledge Graph</strong><input id="graph-filter" type="search" placeholder="Filter nodes"><select id="kind-filter"><option value="">all types</option></select><button id="zoom-in" type="button">+</button><button id="zoom-out" type="button">−</button><button id="fit-graph" type="button">Fit</button><span id="count"></span></header>
<main id="canvas"><svg id="graph" viewBox="0 0 {graph_width} {graph_height}" role="img" aria-label="Skill knowledge graph"></svg></main>
<aside id="node-inspector"><h2>Node inspector</h2><p>Select a node.</p></aside>
<script id="skill-graph-data" type="application/json">{safe_json}</script>
<script>
"use strict";
const data=JSON.parse(document.getElementById("skill-graph-data").textContent);
const svg=document.getElementById("graph"),ns="http://www.w3.org/2000/svg";
const graphWidth={graph_width},graphHeight={graph_height},columns={columns};
const filter=document.getElementById("graph-filter"),kind=document.getElementById("kind-filter");
const inspector=document.getElementById("node-inspector"),positions=new Map(),elements=new Map();
[...new Set(data.nodes.map(n=>n.kind))].sort().forEach(k=>{{const o=document.createElement("option");o.value=k;o.textContent=k;kind.appendChild(o);}});
data.nodes.forEach((n,i)=>{{positions.set(n.id,{{x:100+(i%columns)*190,y:80+Math.floor(i/columns)*130}});}});
data.edges.forEach(e=>{{const a=positions.get(e.source),b=positions.get(e.target);if(!a||!b)return;const line=document.createElementNS(ns,"line");line.setAttribute("x1",a.x);line.setAttribute("y1",a.y);line.setAttribute("x2",b.x);line.setAttribute("y2",b.y);line.setAttribute("class","edge"+(e.active?" active":""));line.dataset.source=e.source;line.dataset.target=e.target;svg.appendChild(line);}});
data.nodes.forEach(n=>{{const p=positions.get(n.id),g=document.createElementNS(ns,"g");g.setAttribute("class","node"+(n.active?" active":""));g.setAttribute("transform",`translate(${{p.x}} ${{p.y}})`);g.tabIndex=0;const c=document.createElementNS(ns,"circle");c.setAttribute("r","34");const t=document.createElementNS(ns,"text");t.setAttribute("text-anchor","middle");t.setAttribute("y","52");t.textContent=n.label.length>24?n.label.slice(0,22)+"…":n.label;g.append(c,t);g.addEventListener("click",()=>inspect(n));g.addEventListener("keydown",e=>{{if(e.key==="Enter")inspect(n);}});svg.appendChild(g);elements.set(n.id,g);}});
function inspect(n){{inspector.replaceChildren();const h=document.createElement("h2");h.textContent=n.label;const p=document.createElement("p");p.textContent=n.kind+(n.active?" · active plan":"");const dl=document.createElement("dl");Object.entries(n.details).forEach(([k,v])=>{{const dt=document.createElement("dt"),dd=document.createElement("dd");dt.textContent=k;dd.textContent=v;dl.append(dt,dd);}});inspector.append(h,p,dl);}}
function apply(){{const q=filter.value.toLowerCase(),k=kind.value;let shown=0;data.nodes.forEach(n=>{{const visible=(!q||(n.label+" "+JSON.stringify(n.details)).toLowerCase().includes(q))&&(!k||n.kind===k);elements.get(n.id).classList.toggle("hidden",!visible);if(visible)shown++;}});svg.querySelectorAll("line").forEach(e=>e.classList.toggle("hidden",elements.get(e.dataset.source)?.classList.contains("hidden")||elements.get(e.dataset.target)?.classList.contains("hidden")));document.getElementById("count").textContent=shown+" nodes";}}
let view={{x:0,y:0,w:graphWidth,h:graphHeight}},drag=null;
function updateView(){{svg.setAttribute("viewBox",`${{view.x}} ${{view.y}} ${{view.w}} ${{view.h}}`);}}
function fitGraph(){{view={{x:0,y:0,w:graphWidth,h:graphHeight}};updateView();}}
function zoom(factor,cx=view.x+view.w/2,cy=view.y+view.h/2){{const w=view.w*factor,h=view.h*factor;view={{x:cx-(cx-view.x)*factor,y:cy-(cy-view.y)*factor,w,h}};updateView();}}
document.getElementById("zoom-in").addEventListener("click",()=>zoom(.8));document.getElementById("zoom-out").addEventListener("click",()=>zoom(1.25));document.getElementById("fit-graph").addEventListener("click",fitGraph);
svg.addEventListener("wheel",e=>{{e.preventDefault();zoom(e.deltaY<0?.85:1.18);}},{{passive:false}});
svg.addEventListener("pointerdown",e=>{{drag={{x:e.clientX,y:e.clientY,view:{{...view}}}};svg.setPointerCapture(e.pointerId);}});svg.addEventListener("pointermove",e=>{{if(!drag)return;const rect=svg.getBoundingClientRect();view.x=drag.view.x-(e.clientX-drag.x)*drag.view.w/rect.width;view.y=drag.view.y-(e.clientY-drag.y)*drag.view.h/rect.height;updateView();}});svg.addEventListener("pointerup",()=>{{drag=null;}});
filter.addEventListener("input",apply);kind.addEventListener("change",apply);fitGraph();apply();
</script>
</body>
</html>
"""
