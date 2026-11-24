from redis.exceptions import RedisError

from src.config.resources import cache, engine
from src.services import cases, inspection, reviews, runs


def new_case(data, user):
    with engine.begin() as db:
        return cases.create(db, data, user["username"])


def _wake_worker(run_id):
    try:
        cache.lpush("workbench:wake", str(run_id))
        cache.ltrim("workbench:wake", 0, 99)
    except RedisError:
        # 数据库持久队列为准，worker 每秒也会轮询。
        pass


def new_run(case_id, data, user):
    with engine.begin() as db:
        run = runs.enqueue(db, case_id, data.parameter, user["username"])
    _wake_worker(run["id"])
    return run


def resume_run(run_id, user):
    run = inspection.resume_run(run_id, user["username"])
    _wake_worker(run_id)
    return run


def pause_run(run_id, user):
    with engine.begin() as db:
        run = runs.pause(db, run_id, user["username"])
    return run


def run_batch(run_id, batch_id, user):
    return inspection.run_batch(run_id, batch_id, user["username"])


def new_review(run_id, data, user):
    with engine.begin() as db:
        return reviews.sign(db, run_id, data, user["username"])
