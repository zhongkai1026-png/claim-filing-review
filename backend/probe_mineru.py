"""MinerU Open API 连通性探测（官方流程）：申请上传链接 → PUT 上传 → 轮询批量结果 → 下载解压。

用法：python probe_mineru.py
"""
import io
import json
import sys
import time
import zipfile

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KEY = "sk-Bi2D60IbUUmbIasnm1Z8SPfLZA4N8SeMQEuVOlY2tcJ8TAwp"
BASE = "https://mineru.net/api/v4"


def make_pdf() -> bytes:
    content = b"BT /F1 20 Tf 72 720 Td (Hello MinerU Test) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = [b"%PDF-1.4\n"]
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(b"".join(out)))
        out.append(b"%d 0 obj\n" % i + obj + b"\nendobj\n")
    xref_pos = len(b"".join(out))
    out.append(b"xref\n0 %d\n" % (len(objects) + 1))
    out.append(b"0000000000 65535 f \n")
    for off in offsets:
        out.append(b"%010d 00000 n \n" % off)
    out.append(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
               % (len(objects) + 1, xref_pos))
    return b"".join(out)


def main():
    print("=" * 56)
    print("  MinerU Open API 连通性探测（官方流程）")
    print("=" * 56)
    headers = {"Authorization": f"Bearer {KEY}"}

    # 1. 申请上传链接
    print("\n[1] 申请上传链接 -> POST /file-urls/batch")
    try:
        r = httpx.post(
            f"{BASE}/file-urls/batch",
            headers={**headers, "Content-Type": "application/json"},
            json={"files": [{"name": "test.pdf", "data_id": "probe001",
                             "is_ocr": True}],
                  "model_version": "vlm"},
            timeout=60,
        )
    except Exception as e:
        print(f"    ❌ 请求异常: {e}")
        return
    print(f"    HTTP {r.status_code}")
    print(f"    body: {r.text[:400]}")
    if r.status_code != 200:
        print("\n❌ 申请链接失败")
        return
    j = r.json()
    if j.get("code") != 0:
        print(f"    ❌ 业务错误: {j.get('msg')}")
        return
    d = j["data"]
    batch_id = d.get("batch_id")
    urls = d.get("file_urls") or []
    print(f"    ✅ batch_id = {batch_id}")
    print(f"    ✅ 上传链接 = {urls}")

    # 2. PUT 上传
    print("\n[2] PUT 上传文件（自动触发解析）")
    pdf = make_pdf()
    try:
        r2 = httpx.put(urls[0], content=pdf, timeout=120)
        print(f"    HTTP {r2.status_code}  body: {r2.text[:200]}")
        if r2.status_code != 200:
            print("\n❌ 上传失败")
            return
        print("    ✅ 上传成功，等待自动解析…")
    except Exception as e:
        print(f"    ❌ 上传异常: {e}")
        return

    # 3. 轮询批量结果
    print("\n[3] 轮询批量结果 -> GET /extract-results/batch/{batch_id}")
    for i in range(40):
        time.sleep(4)
        try:
            r3 = httpx.get(f"{BASE}/extract-results/batch/{batch_id}",
                           headers=headers, timeout=30)
            j3 = r3.json()
            if j3.get("code") != 0:
                print(f"    [{i}] code={j3.get('code')} msg={j3.get('msg')}")
                time.sleep(2)
                continue
            results = j3.get("data", {}).get("extract_result") or []
            for item in results:
                state = item.get("state")
                print(f"    [{i}] {item.get('file_name')}: state={state}"
                      + (f" err={item.get('err_msg')}" if state == "failed" else ""))
                if state == "done":
                    url = item.get("full_zip_url")
                    print(f"    ✅ 解析完成，zip: {url}")
                    # 4. 下载解压
                    print("\n[4] 下载并解压结果")
                    r4 = httpx.get(url, timeout=120)
                    z = zipfile.ZipFile(io.BytesIO(r4.content))
                    names = z.namelist()
                    print(f"    包内文件: {names}")
                    for n in names:
                        if n.endswith(".md"):
                            text = z.read(n).decode("utf-8", "ignore")
                            print(f"    --- {n} ---")
                            print(text[:300])
                    print("\n✅ 全链路测试通过！")
                    return
            if all(x.get("state") == "failed" for x in results):
                print("    ❌ 全部解析失败")
                return
        except Exception as e:
            print(f"    [{i}] 轮询异常: {e}")
    print("\n❌ 轮询超时")


if __name__ == "__main__":
    main()
