#!/usr/bin/env python3
"""Generate a local browser UI for manual review of dichotic errors."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[2]


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>双耳错误人工复核</title>
<style>
:root{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#172033}
body{margin:0;background:#f3f6fa}header{position:sticky;top:0;z-index:2;background:#17365d;color:white;padding:14px 22px}
h1{margin:0 0 8px;font-size:22px}.toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
button{border:0;border-radius:7px;padding:9px 14px;cursor:pointer;font-weight:650}.primary{background:#ffd166}.secondary{background:#e6edf7;color:#17365d}.danger{background:#ffe0e0;color:#8a1c1c}
main{max-width:1080px;margin:22px auto;padding:0 16px 50px}.card{background:white;border-radius:12px;box-shadow:0 3px 16px #18315318;padding:20px}
.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px;margin-bottom:16px}.meta div{background:#f6f8fb;border-radius:7px;padding:9px}.meta b{display:block;color:#4d5d75;font-size:12px;margin-bottom:3px}
.audio-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin:18px 0}.audio-item{border:1px solid #d9e1ec;border-radius:9px;padding:10px}.audio-item strong{display:block;margin-bottom:7px}audio{width:100%}
.form-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}label{display:block;font-weight:650;color:#263750}select,textarea{width:100%;box-sizing:border-box;margin-top:6px;padding:8px;border:1px solid #bdc9d8;border-radius:6px;background:white}textarea{min-height:90px;resize:vertical}
.hint{color:#5d6b7e;font-size:13px;line-height:1.5}.status{font-weight:700}.complete{color:#16804d}.incomplete{color:#b45b00}.footer-nav{display:flex;justify-content:space-between;margin-top:18px}
@media(max-width:600px){header{position:static}}
</style>
</head>
<body>
<header><h1>同说话人双耳错误人工复核</h1><div class="toolbar">
<button class="secondary" id="prev">上一条</button><button class="secondary" id="next">下一条</button>
<button class="secondary" id="nextUnreviewed">下一个未完成</button><button class="primary" id="exportCsv">导出已填CSV</button>
<button class="danger" id="clearCurrent">清空当前填写</button><span id="progress"></span></div></header>
<main><div class="card" id="card"></div></main>
<script>
const rows=__ROWS__;
const storageKey="dichotic-review-2026-07-23";
const fields=[
 ["manual_target_word_audible_yes_no","目标词是否清楚可听？"],
 ["manual_alignment_center_ok_yes_no","目标词是否在切片中心附近？"],
 ["manual_transcript_matches_audio_yes_no","转录/目标词是否与音频一致？"],
 ["manual_audio_quality_ok_yes_no","录音质量是否可接受？"],
 ["manual_label_equivalent_yes_no","预测词是否可视为标签等价？"],
 ["manual_exclude_for_objective_reason_yes_no","是否有客观理由排除该刺激？"]
];
let state={};try{state=JSON.parse(localStorage.getItem(storageKey)||"{}") }catch(_){state={}}
let index=0;
const val=(r,f)=>(state[r.trial_id]||{})[f]??r[f]??"";
const complete=r=>fields.slice(0,4).every(([f])=>["yes","no","uncertain"].includes(val(r,f)));
function save(r,f,v){state[r.trial_id]=state[r.trial_id]||{};state[r.trial_id][f]=v;localStorage.setItem(storageKey,JSON.stringify(state));progress()}
function esc(v){return String(v??"").replace(/[&<>\"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function selector(r,f,label){const current=val(r,f);const opts=[["","未填"],["yes","Yes"],["no","No"],["uncertain","Uncertain"]];return `<label>${esc(label)}<select data-field="${f}">${opts.map(([v,t])=>`<option value="${v}" ${current===v?"selected":""}>${t}</option>`).join("")}</select></label>`}
function render(){const r=rows[index];const status=complete(r)?'<span class="status complete">已完成基本判断</span>':'<span class="status incomplete">待完成</span>';
 const aud=[["01 Target",r.audio_target],["02 Opposite",r.audio_opposite],["03 Cue",r.audio_cue],["04 Dichotic",r.audio_dichotic]];
 document.getElementById("card").innerHTML=`<h2>#${r.review_order} / ${rows.length} ${status}</h2>
 <div class="meta"><div><b>错误类型</b>${esc(r.error_class)}</div><div><b>Target / Prediction</b>${esc(r.cued_word)} → ${esc(r.pred_dichotic)}</div><div><b>Opposite</b>${esc(r.opposite_word)}</div><div><b>Cue ear</b>${esc(r.cue_ear)}</div><div><b>Diotic prediction</b>${esc(r.pred_diotic_clean)}</div><div><b>p(target) / p(opposite)</b>${Number(r.p_cued_dichotic).toFixed(4)} / ${Number(r.p_opposite_dichotic).toExponential(2)}</div><div><b>中央2秒有效电平差</b>${Number(r.effective_cued_minus_opposite_db).toFixed(2)} dB</div><div><b>字符串相似度</b>${Number(r.target_prediction_string_similarity).toFixed(3)}</div></div>
 <p class="hint">顺序：先听target判断词和对齐，再听opposite与cue，最后听dichotic。不要因模型答错就判定刺激无效。</p>
 <div class="audio-grid">${aud.map(([n,f])=>`<div class="audio-item"><strong>${n}</strong><audio controls preload="none" src="${encodeURI(f)}"></audio></div>`).join("")}</div>
 <div class="form-grid">${fields.map(([f,l])=>selector(r,f,l)).join("")}</div><label style="margin-top:14px">备注<textarea data-field="manual_notes">${esc(val(r,"manual_notes"))}</textarea></label>
 <div class="footer-nav"><button class="secondary" onclick="move(-1)">上一条</button><button class="secondary" onclick="move(1)">下一条</button></div>`;
 document.querySelectorAll("[data-field]").forEach(el=>el.addEventListener("input",()=>save(r,el.dataset.field,el.value)));progress()}
function move(d){index=Math.max(0,Math.min(rows.length-1,index+d));render();window.scrollTo(0,0)}
function progress(){document.getElementById("progress").textContent=`已完成 ${rows.filter(complete).length}/${rows.length}；当前 ${index+1}/${rows.length}`}
function nextUnreviewed(){for(let s=1;s<=rows.length;s++){const c=(index+s)%rows.length;if(!complete(rows[c])){index=c;render();return}}alert("所有项目都已完成基本判断。")}
function csvEscape(v){const t=String(v??"");return /[\",\n\r]/.test(t)?`"${t.replaceAll('"','""')}"`:t}
function exportCsv(){const cols=Object.keys(rows[0]).filter(c=>!c.startsWith("audio_"));const lines=[cols.map(csvEscape).join(",")];rows.forEach(r=>{const m={...r,...(state[r.trial_id]||{})};lines.push(cols.map(c=>csvEscape(m[c])).join(","))});const blob=new Blob(["\ufeff"+lines.join("\n")+"\n"],{type:"text/csv;charset=utf-8"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="dichotic_manual_review_completed.csv";a.click();URL.revokeObjectURL(a.href)}
document.getElementById("prev").onclick=()=>move(-1);document.getElementById("next").onclick=()=>move(1);document.getElementById("nextUnreviewed").onclick=nextUnreviewed;document.getElementById("exportCsv").onclick=exportCsv;
document.getElementById("clearCurrent").onclick=()=>{if(confirm("清空当前填写？")){delete state[rows[index].trial_id];localStorage.setItem(storageKey,JSON.stringify(state));render()}};
document.addEventListener("keydown",e=>{if(["TEXTAREA","SELECT"].includes(e.target.tagName))return;if(e.key==="ArrowLeft")move(-1);if(e.key==="ArrowRight")move(1)});render();
</script></body></html>
"""


def one_audio(directory: Path, order: int, pattern: str) -> str:
    matches = sorted(directory.glob(f"{order:03d}_*_{pattern}.wav"))
    if len(matches) != 1:
        raise ValueError(
            f"review_order {order}: expected one *_{pattern}.wav; found {len(matches)}"
        )
    return matches[0].name


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--review",
        type=Path,
        default=REPO / "双耳分析任务/results/dichotic_manual_review.csv",
    )
    ap.add_argument(
        "--audio-dir",
        type=Path,
        default=REPO / "双耳分析任务/local_review_audio",
    )
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    review = pd.read_csv(args.review, keep_default_na=False)
    if len(review) != 93:
        raise ValueError(f"expected 93 review rows, found {len(review)}")
    records = review.to_dict("records")
    for record in records:
        order = int(record["review_order"])
        record["audio_target"] = one_audio(args.audio_dir, order, "01_target")
        record["audio_opposite"] = one_audio(args.audio_dir, order, "02_opposite-*")
        record["audio_cue"] = one_audio(args.audio_dir, order, "03_cue")
        record["audio_dichotic"] = one_audio(args.audio_dir, order, "04_dichotic")

    payload = json.dumps(records, ensure_ascii=False).replace("</", "<\\/")
    output = args.out or args.audio_dir / "review.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(HTML.replace("__ROWS__", payload), encoding="utf-8")
    print(f"review page: {output}")
    print(f"rows: {len(records)}; audio files linked: {len(records) * 4}")


if __name__ == "__main__":
    main()
