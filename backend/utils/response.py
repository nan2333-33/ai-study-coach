"""统一接口返回结构：{"code":0,"data":...,"msg":"ok"}，对齐 PRD。"""
from flask import jsonify


def ok(data=None, msg="ok"):
    return jsonify({"code": 0, "data": data, "msg": msg})


def fail(msg="error", code=1, data=None):
    # business code 同时作为 HTTP 状态码（4xx/5xx 范围内），便于前端/网关识别
    http_status = code if 400 <= code <= 599 else 400
    return jsonify({"code": code, "data": data, "msg": msg}), http_status
