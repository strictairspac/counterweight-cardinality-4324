import { api } from "../api/workbench.js";
import { BatchStates } from "../constants/states.js";
import { empty, pageHeading, section } from "../components/common/panel.js";
import { status } from "../components/common/status.js";
import { table } from "../components/common/table.js";
import { poll } from "../hooks/poll.js";
import { el } from "../utils/dom.js";
import { time } from "../utils/format.js";

function actionButton(label, testId, onClick, {primary = false} = {}) {
  const issue = el("span", {class: "feedback action-error", "data-action-error": testId}, "");
  const button = el("button", {type: "button", "data-testid": testId, class: primary ? "primary" : ""}, label);
  button.addEventListener("click", async () => {
    issue.textContent = "";
    button.disabled = true;
    try {
      await onClick();
    } catch (error) {
      issue.textContent = error.message;
      button.disabled = false;
    }
  });
  return el("span", {class: "action"}, button, issue);
}

function progressLine(run) {
  const p = run.progress || {};
  if (!p.checks_total) return null;
  return el("p", {"data-testid": "run-progress", class: "progress-line"},
    `复检号结果 ${p.checks_done}/${p.checks_total}`,
    ` · 原批次 ${p.batches_done}/${p.batches_total}`,
    ` · 入库实测 ${p.measurements_total} 条（同重量档+槽宽档共用）`,
  );
}

function codeChips(run) {
  if (!run.items?.length) return null;
  return el("div", {class: "code-chips", "data-testid": "item-chips"},
    run.items.map(item => el("span", {
      class: `chip chip-${item.status}`,
      "data-code": item.code,
      title: `${item.mass} / ${item.slot_band}`,
    }, `${item.code}${item.actual_count != null ? ` · ${item.actual_count}` : ""}`)));
}

function batchesBlock(run, user, onChange) {
  if (!run.batches?.length) return null;
  const operator = user?.role === "operator";
  const rows = run.batches.map(batch => {
    const codes = (run.items || []).filter(item => item.batch_id === batch.id).map(item => item.code).join("、");
    const act = operator && batch.status !== "done"
      ? actionButton("复检这批", `run-batch-${batch.id}`, async () => {
          await api.runBatch(run.id, batch.id);
          await onChange();
        })
      : el("span", {class: "muted"}, batch.status === "done" ? "实测已入库" : "");
    return [
      el("span", {}, batch.title),
      el("span", {class: "batch-codes"}, codes),
      el("span", {"data-testid": `batch-status-${batch.id}`}, BatchStates[batch.status] || batch.status),
      act,
    ];
  });
  return section("原批次进度（中断后按此分批续跑，并发重跑不重复实测）",
    table(["批次", "复检号", "状态", "操作"], rows, "复检分批"));
}

function buildDetail(run, user, onChange) {
  const operator = user?.role === "operator";

  const buttons = [];
  if (operator && run.status !== "done") {
    buttons.push(actionButton("续跑剩余批次", "resume-run", async () => {
      const updated = await api.resumeRun(run.id);
      await onChange(updated);
    }, {primary: true}));
    if (run.status !== "paused") {
      buttons.push(actionButton("中断（当前批后停）", "pause-run", async () => {
        await api.pauseRun(run.id);
        await onChange();
      }));
    }
  }
  if (operator && run.status === "done") {
    buttons.push(actionButton("重跑同一批（沿用入库实测，不重复测量）", "rerun-run", async () => {
      const updated = await api.resumeRun(run.id);
      await onChange(updated);
    }));
  }

  const head = el("div", {class: "stack", id: "run-state"},
    el("div", {class: "row"}, status(run.status), el("span", {class: "muted"}, `#${run.id} · 参数 ${run.parameter}`)),
    progressLine(run),
    codeChips(run),
    run.status === "failed" ? el("p", {class: "feedback", role: "alert"}, run.failure || "处理失败") : null,
    run.status === "paused"
      ? el("p", {}, "已中断：已入库的实测数会直接沿用，点击「续跑剩余批次」从未完成的原批次继续。")
      : run.status === "queued"
        ? el("p", {}, "后台正在处理，页面会自动更新。也可以立即点「续跑剩余批次」在本页直接跑完；已入库实测会直接沿用。")
        : run.result ? el("p", {}, run.result.summary) : null,
    buttons.length ? el("div", {class: "button-row"}, buttons) : null,
    run.status === "done" ? el("a", {class: "button primary", href: `#evidence/${run.id}`, "data-testid": "view-certificate"}, "查看可签核的容量证明") : null,
  );

  return el("div", {class: "stack run-detail", "data-testid": "run-detail"},
    section(run.case_title, head),
    batchesBlock(run, user, onChange));
}

export async function runsPage(config, route, signal, user) {
  const items = await api.runs();
  const initialId = route.id ?? items[0]?.id ?? null;
  let latest = initialId ? await api.run(initialId, signal) : null;

  const detailHost = el("div", {class: "stack"});
  async function render(next) {
    if (next) latest = next;
    if (!latest) {
      detailHost.replaceChildren(empty("进入资料页，选用一个业务样本并提交执行。"));
      return false;
    }
    const full = next ?? await api.run(latest.id, signal);
    latest = full;
    detailHost.replaceChildren(buildDetail(full, user, render));
    const badge = document.querySelector(`[data-run="${full.id}"] .status`);
    if (badge) badge.replaceWith(status(full.status));
    return full.status === "queued";
  }
  await render(latest);
  if (latest?.status === "queued") {
    poll(async () => {
      try {
        return await render();
      } catch (error) {
        // 导航离开会触发 abort；其余瞬时错误停止本轮轮询，可手动刷新/续跑。
        return false;
      }
    }, signal);
  }

  return el("div", {class: "page"},
    pageHeading(config.modules[2], config.parameter_label),
    detailHost,
    section("执行批次", items.length ? table(["资料", "编号", "参数", "状态", "提交时间"],
      items.map(run => [el("a", {"data-run": run.id, href: `#runs/${run.id}`}, run.case_title), run.id,
        run.parameter, el("span", {"data-run": run.id}, status(run.status)), time(run.created_at)]), "执行批次") :
      empty("暂无执行记录。")));
}
