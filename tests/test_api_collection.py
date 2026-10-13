"""API collection (Postman v2.1): lengkap, tidak usang, dan benar-benar berjalan terhadap API."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core.config import AppConfig
from app.ingest.service import ingest_direktori
from app.main import create_app
from scripts import build_api_collection as bac
from tests.conftest import make_settings
from tests.helpers import SEED_DIR

KOLEKSI = bac.bangun_collection()


def semua_item(node: dict) -> list[dict]:
    hasil = []
    for it in node["item"]:
        hasil += semua_item(it) if "item" in it else [it]
    return hasil


def normal(segmen: list[str]) -> str:
    return "/" + "/".join("{}" if re.fullmatch(r"\{+\w+\}+", s) else s for s in segmen)


# ------------------------------------------------------------------ struktur & kelengkapan


def test_skema_postman_v21_dan_struktur_dasar():
    assert KOLEKSI["info"]["schema"] == bac.SCHEMA
    assert KOLEKSI["info"]["name"] == "JalurKu API"
    assert KOLEKSI["auth"]["type"] == "bearer"
    assert KOLEKSI["auth"]["bearer"][0]["value"] == "{{token}}"
    item = semua_item(KOLEKSI)
    assert len(item) >= 60
    for it in item:
        r = it["request"]
        assert r["method"] in {"GET", "POST", "PUT", "DELETE"}
        assert r["url"]["raw"].startswith("{{baseUrl}}/api/v1/")
        assert r["url"]["host"] == ["{{baseUrl}}"] and r["url"]["path"][:2] == ["api", "v1"]
        assert r["description"]


def test_nama_request_unik_dalam_satu_folder():
    for folder in KOLEKSI["item"]:
        nama = [i["name"] for i in folder["item"]]
        assert len(nama) == len(set(nama)), folder["name"]


def test_semua_endpoint_api_tercakup_dan_tidak_ada_yang_usang(app_config: AppConfig):
    app = create_app(make_settings(), app_config)
    api = {
        (metode.upper(), normal(path.strip("/").split("/")))
        for path, ops in app.openapi()["paths"].items()
        for metode in ops
    }
    koleksi = {
        (it["request"]["method"], normal(it["request"]["url"]["path"]))
        for it in semua_item(KOLEKSI)
    }
    assert api - koleksi == set(), f"endpoint belum ada di koleksi: {sorted(api - koleksi)}"
    assert koleksi - api == set(), f"request koleksi tanpa endpoint: {sorted(koleksi - api)}"


def test_semua_variabel_terdefinisi():
    kunci_env: set[str] = set()
    for nama, url in bac.ENVIRONMENT.values():
        env = bac.bangun_environment(nama, url)
        assert {v["key"] for v in env["values"]} == {"baseUrl", "adminKey"}
        kunci_env |= {v["key"] for v in env["values"]}
    terdefinisi = set(bac.VARIABEL_KOLEKSI) | kunci_env
    assert bac.variabel_dirujuk() <= terdefinisi, bac.variabel_dirujuk() - terdefinisi


def test_bodi_json_valid_dan_placeholder_hanya_di_dalam_string():
    n = 0
    for it in semua_item(KOLEKSI):
        body = it["request"].get("body")
        if body and body["mode"] == "raw":
            json.loads(body["raw"])  # gagal bila ada {{var}} di luar tanda kutip
            n += 1
    assert n >= 40


def test_setiap_request_punya_uji_status_dan_token_ditangkap():
    for it in semua_item(KOLEKSI):
        skrip = "\n".join(it["event"][0]["script"]["exec"])
        assert "pm.response.to.have.status(" in skrip, it["name"]
    sesi = next(i for i in semua_item(KOLEKSI) if i["name"] == "Buat sesi (consent)")
    assert 'pm.collectionVariables.set("token", j.token);' in sesi["event"][0]["script"]["exec"]
    simpan = next(i for i in semua_item(KOLEKSI) if i["name"] == "Simpan strategi SNBT")
    assert (
        'pm.collectionVariables.set("strategyId", j.strategy_id);'
        in simpan["event"][0]["script"]["exec"]
    )


def test_autentikasi_per_request():
    item = {i["name"]: i["request"] for i in semua_item(KOLEKSI)}
    assert item["Cek kesehatan"]["auth"] == {"type": "noauth"}
    assert item["Buat sesi (consent)"]["auth"] == {"type": "noauth"}
    assert "auth" not in item["Baca profil"]  # mewarisi bearer {{token}} dari koleksi
    admin = item["Ingest profesi (contoh)"]
    assert admin["auth"] == {"type": "noauth"}
    assert {"key": "X-Admin-Key", "value": "{{adminKey}}", "type": "text"} in admin["header"]


def test_unggah_berkas_formdata_dengan_query_proses():
    r = next(i for i in semua_item(KOLEKSI) if i["name"] == "Unggah PDF sumber RAG")["request"]
    assert r["body"]["mode"] == "formdata" and r["body"]["formdata"][0]["key"] == "berkas"
    assert r["url"]["raw"].endswith("/admin/dokumen/{{dokumenId}}/berkas?proses=false")


def test_param_nonaktif_tidak_masuk_url_mentah():
    r = next(i for i in semua_item(KOLEKSI) if i["name"] == "Daftar prodi")["request"]
    assert any(q.get("disabled") for q in r["url"]["query"])
    assert "q=komputer" not in r["url"]["raw"] and "rumpun=Teknik" in r["url"]["raw"]


def test_tanpa_rahasia_di_berkas():
    for nama, url in bac.ENVIRONMENT.values():
        env = bac.bangun_environment(nama, url)
        assert all(v["value"] == "" for v in env["values"] if v["key"] == "adminKey")
        assert next(v for v in env["values"] if v["key"] == "adminKey")["type"] == "secret"
    assert bac.VARIABEL_KOLEKSI["token"] == "" and bac.VARIABEL_KOLEKSI["strategyId"] == ""
    teks = json.dumps(KOLEKSI)
    assert not re.search(r"Bearer [A-Za-z0-9_\-]{20,}|AIza[0-9A-Za-z_\-]{20,}", teks)


# ------------------------------------------------------------------ tidak usang (drift)


def test_berkas_di_repo_sama_dengan_hasil_generator():
    for nama, isi in bac.berkas_yang_dihasilkan().items():
        path = bac.OUT_DEFAULT / nama
        assert path.is_file(), f"{nama} belum dibuat: python -m scripts.build_api_collection"
        assert json.loads(path.read_text(encoding="utf-8")) == isi, (
            f"{nama} usang: jalankan python -m scripts.build_api_collection"
        )


def test_cli_cek_mendeteksi_berkas_hilang_atau_usang(tmp_path: Path):
    assert bac.main(["--out", str(tmp_path), "--cek"]) == 1  # belum ada
    assert bac.main(["--out", str(tmp_path)]) == 0
    assert bac.main(["--out", str(tmp_path), "--cek"]) == 0
    (tmp_path / "JalurKu.postman_collection.json").write_text("{}", encoding="utf-8")
    assert bac.main(["--out", str(tmp_path), "--cek"]) == 1


def test_bodi_persona_sinkron_dengan_config_personas():
    from app.services import persona as modul

    for req, nama in (
        (bac.R_PROFIL_RANI, "rani"),
        (bac.R_PROFIL_DIMAS, "dimas"),
        (bac.R_PROFIL_BUDI, "budi"),
        (bac.R_PROFIL_SINTA, "sinta"),
    ):
        assert req.body == modul.muat(nama).profil


# ------------------------------------------------------------------ replay terhadap API sungguhan


@pytest.mark.db
def test_seluruh_koleksi_berjalan_terhadap_api(clean_db: Engine, app_config: AppConfig):
    """Putar ulang semua request berurutan (seperti Collection Runner) dan cocokkan status, kunci
    respons, temuan, `yakin`, serta penangkapan variabel dengan yang dideklarasikan di koleksi."""
    with Session(clean_db) as db:
        assert all(h.ok for h in ingest_direktori(db, SEED_DIR))
    app = create_app(make_settings(admin_key="kunci-uji"), app_config, clean_db)
    vars_ = {**bac.VARIABEL_KOLEKSI, "adminKey": "kunci-uji"}

    def sub(teks: str) -> str:
        return re.sub(r"\{\{(\w+)\}\}", lambda m: vars_[m.group(1)], teks)

    dijalankan = 0
    with TestClient(app, raise_server_exceptions=False) as c:
        for folder in bac.semua_folder():
            for r in folder.isi:
                if not r.replay:
                    continue
                headers = {}
                if r.auth == "bearer" and vars_["token"]:
                    headers["Authorization"] = f"Bearer {vars_['token']}"
                if r.auth == "admin":
                    headers["X-Admin-Key"] = vars_["adminKey"]
                body = json.loads(sub(json.dumps(r.body))) if r.body is not None else None
                params = {k: sub(v) for k, v, aktif in r.query if aktif}
                resp = c.request(
                    r.method, "/api/v1" + sub(r.path), params=params, json=body, headers=headers
                )
                konteks = f"[{folder.nama}] {r.nama}: {resp.status_code} {resp.text[:200]}"
                assert resp.status_code == r.status, konteks
                if r.status == 204:
                    dijalankan += 1
                    continue
                data = resp.json()
                assert set(r.kunci) <= set(data), konteks
                if r.temuan:
                    assert r.temuan in {t["kode"] for t in data["temuan"]}, konteks
                if r.yakin is not None:
                    assert data["yakin"] is r.yakin, konteks
                for variabel, kunci in r.tangkap:
                    assert data[kunci], konteks
                    vars_[variabel] = data[kunci]
                dijalankan += 1
    assert dijalankan >= len(bac.semua_request()) - 1  # semua kecuali unggah berkas
