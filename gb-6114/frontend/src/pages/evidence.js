import { api } from "../api/workbench.js";
import { errorText, field } from "../components/common/fields.js";
import { empty, pageHeading, section } from "../components/common/panel.js";
import { resultTable, table } from "../components/common/table.js";
import { submit } from "../hooks/submit.js";
import { el } from "../utils/dom.js";
import { cell, download, time } from "../utils/format.js";

function reviewForm(id, saved) {
  const form = el("form", {id: "review-form"},
    field("复核意见", el("textarea", {name: "note", required: true, minlength: 3, maxlength: 500, rows: 3})),
    errorText(), el("button", {type: "submit"}, "签署复核"));
  submit(form, async values => saved(await api.submitReview(id, {note: values.get("note")})));
  return form;
}

function signature(review) {
  return el("div", {"data-testid": "reviewed", class: "signature"},
    el("strong", {}, `已签署 · ${review.actor}`), el("p", {}, review.note), el("time", {}, time(review.created_at)));
}

function certificateNumber(run) {
  return `RL-${String(run.id).padStart(4, "0")}-${(run.digest || "").slice(0, 10).toUpperCase()}`;
}

function ledgerSection(run) {
  const records = run.measurements || [];
  if (!records.length) return null;
  return section("实测数台账（同一重量档+槽宽档只测一次，复检号全部保留）",
    table(["重量档", "槽宽档", "入库实测数", "共用复检号", "共用情况"], records.map(m => [
      m.mass,
      m.slot_band,
      el("strong", {"data-testid": "measurement-value"}, String(m.actual_count)),
      (m.codes || []).join("、"),
      m.shared ? `${m.codes.length} 个复检号共用一条实测数` : "单个复检号",
    ]), "实测数台账"));
}

function certificate(run, review, user, reload) {
  const issue = errorText();
  const button = el("button", {type: "button", onclick: async () => {
    button.disabled = true;
    issue.textContent = "";
    try {
      await download(await api.export(run.id), `evidence-${run.id}.json`);
    } catch (error) {
      issue.textContent = error.message;
    } finally {
      button.disabled = false;
    }
  }}, "导出容量证明（JSON）");

  const signing = el("div", {"data-testid": "signing-area"});
  if (review) signing.replaceChildren(signature(review));
  else if (user.role === "reviewer") {
    signing.replaceChildren(reviewForm(run.id, data => {
      signing.replaceChildren(signature(data));
      reload();
    }));
  } else signing.replaceChildren(empty("待复核员签署，每个批次仅可签署一次。"));

  return [
    el("section", {class: "feature certificate", "data-testid": "certificate"},
      el("div", {},
        el("p", {class: "overline"}, "可签核文件"),
        el("h2", {}, "配重复检容量证明"),
        el("p", {}, `证明编号：${certificateNumber(run)}`),
        el("p", {}, run.result.summary)),
      el("aside", {},
        el("h3", {}, "防伪摘要 SHA-256"),
        el("code", {class: "digest"}, run.digest),
        el("p", {class: "muted"}, `出具时间：${time(run.finished_at)}`))),
    el("dl", {class: "metrics"}, Object.entries(run.result.metrics).map(([label, value]) =>
      el("div", {}, el("dt", {}, label), el("dd", {}, cell(value))))),
    section(`全部复检号结果明细（${run.progress.checks_done}/${run.progress.checks_total}）`,
      run.result.rows.length ? resultTable(run.result.rows) : empty("此批次无明细。")),
    ledgerSection(run),
    section("复核签署", signing),
    el("div", {class: "button-row"}, button, issue),
  ];
}

function gate(run, user, reload) {
  const p = run.progress || {checks_done: 0, checks_total: 0, batches_done: 0, batches_total: 0};
  const issue = errorText();
  const actions = [el("a", {class: "button primary", href: `#runs/${run.id}`}, "前往续跑 / 分批复检")];
  if (user.role === "operator") {
    const resume = el("button", {type: "button", "data-testid": "evidence-resume"}, "续跑剩余批次并刷新");
    resume.addEventListener("click", async () => {
      resume.disabled = true;
      try {
        const updated = await api.resumeRun(run.id);
        if (updated.status === "done") reload();
        else issue.textContent = "仍有批次未完成，可再次续跑。";
      } catch (error) {
        issue.textContent = error.message;
      } finally {
        resume.disabled = false;
      }
    });
    actions.unshift(resume);
  }
  return el("div", {class: "stack", "data-testid": "certificate-pending"},
    section("复检容量证明（尚未出具）",
      el("p", {}, `全部复检号都有结果后，才会生成一份可签核的容量证明。当前 ${p.checks_done}/${p.checks_total} 个复检号已有结果，原批次完成 ${p.batches_done}/${p.batches_total}。`),
      el("div", {class: "button-row"}, actions),
      issue),
    p.checks_total ? section("复检号进度", el("div", {class: "code-chips"},
      (run.items || []).map(item => el("span", {
        class: `chip chip-${item.status}`,
        "data-code": item.code,
      }, `${item.code}${item.actual_count != null ? ` · ${item.actual_count}` : ""}`)))) : null);
}

export async function evidencePage(config, user, route) {
  const runs = await api.runs();
  // 默认展示最近一份已完成的证明（保持原交互）；没有已完成批次时展示最新批次的门槛与进度。
  const doneRuns = runs.filter(item => item.status === "done");
  const selectedId = route.id ?? doneRuns[0]?.id ?? runs[0]?.id ?? null;
  if (!selectedId) {
    return el("div", {class: "page"},
      pageHeading(config.modules[3], null),
      empty("成功执行一个批次、且全部复检号都有结果后，可以查看、签核和下载容量证明。"),
      el("a", {href: "#runs"}, config.modules[2]));
  }

  let run = await api.run(selectedId);
  let review = await api.review(run.id).catch(() => null);
  const host = el("div", {class: "page evidence"});

  const options = el("select", {
    "aria-label": "选择执行批次",
    onchange: event => { location.hash = `evidence/${event.target.value}`; },
  }, runs.map(item => el("option", {value: item.id, selected: item.id === run.id},
    `#${item.id} ${item.case_title}（${({queued: "进行中", paused: "已中断", done: "已完成", failed: "失败"})[item.status] || item.status}）`)));

  async function reload() {
    run = await api.run(run.id);
    review = await api.review(run.id).catch(() => null);
    render();
  }

  function render() {
    const ready = run.status === "done" && run.progress?.all_results && run.result;
    const body = ready ? certificate(run, review, user, reload) : [gate(run, user, reload)];
    host.replaceChildren(pageHeading(config.modules[3], run.case_title), options, ...body);
  }

  render();
  return host;
}
