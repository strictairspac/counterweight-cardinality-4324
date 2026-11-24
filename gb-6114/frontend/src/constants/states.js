export const States = Object.freeze({
  queued: "等待执行", paused: "已中断", done: "已完成", failed: "执行失败",
});

export const BatchStates = Object.freeze({
  pending: "待复检", running: "复检中", done: "本批完成",
});

export const Actions = Object.freeze({
  create_case: "登记资料",
  enqueue: "提交执行",
  resume: "续跑批次",
  pause: "中断批次",
  done: "执行完成",
  failed: "执行失败",
  review: "复核签署",
});
