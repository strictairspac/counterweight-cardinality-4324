CELLS = [("轻档", "紧槽"), ("轻档", "宽槽"), ("重档", "紧槽"), ("重档", "宽槽")]
CHECKS = [
    {"code": f"FL-2411-{index:02}", "mass": mass, "slot": slot}
    for index, (mass, slot) in enumerate(CELLS, 1)
]

# 同一重量档+槽宽档对应多个复检号：实测数共用，复检号一个都不能丢。
SHARED_CHECKS = [
    {"code": "FL-2411-01", "mass": "轻档", "slot": "紧槽"},
    {"code": "FL-2411-02", "mass": "轻档", "slot": "宽槽"},
    {"code": "FL-2411-03", "mass": "重档", "slot": "紧槽"},
    {"code": "FL-2411-04", "mass": "重档", "slot": "宽槽"},
    {"code": "FL-2411-05", "mass": "轻档", "slot": "紧槽"},
    {"code": "FL-2411-06", "mass": "重档", "slot": "宽槽"},
]


def lots(calibration, inspection, checks=None):
    return {
        "calibration": [
            {"mass": mass, "slot": slot, "count": count}
            for (mass, slot), count in zip(CELLS, calibration)
        ],
        "inspection": [
            {"mass": mass, "slot": slot, "count": count}
            for (mass, slot), count in zip(CELLS, inspection)
        ],
        "checks": CHECKS if checks is None else checks,
    }


FIXTURES = [
    {
        "code": "FL-2411-MIX",
        "title": "货梯配重加严抽查",
        "description": "同供应线两项公差随工装成对偏移，估算复检会取到多少检测记录。",
        "payload": lots([45, 5, 5, 45], [54, 6, 6, 54]),
    },
    {
        "code": "FL-2411-DRIFT",
        "title": "临时工装配对漂移",
        "description": "校准沿用原供应线，待查批次换了临时工装，检测证据应暴露统计失配。",
        "payload": lots([45, 5, 5, 45], [6, 54, 54, 6]),
    },
    {
        "code": "FL-2411-SHARE",
        "title": "同档多复检号共用实测",
        "description": "六个复检号只落在四个档位组合上，同重量档与槽宽档共用一条入库实测数，可分批续跑。",
        "payload": lots([45, 5, 5, 45], [54, 6, 6, 54], SHARED_CHECKS),
    },
]
