# 复检组分两个工位排查，每批稳定放 2 个复检号；
# 提交时确定的分批顺序就是「原批次」，续跑不重新切分。
BATCH_SIZE = 2


def plan_batches(checks, size=BATCH_SIZE):
    """按复检号原始顺序切成连续小批，返回 [[Check, ...], ...]。"""
    return [list(checks[index:index + size]) for index in range(0, len(checks), size)]
