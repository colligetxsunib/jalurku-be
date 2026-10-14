"""Task 3: sesi tamu, token, consent, rate limit, pembersihan (kriteria penerimaan 7.1)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from app.core.config import AppConfig, Batas
from app.core.rate_limit import SlidingWindowLimiter, ip_klien
from app.core.security import buat_token, hash_token
from app.db.models import Profil, QueryLog, Sesi, Strategi
from app.main import create_app
from app.services.sessions import hapus_kedaluwarsa
from tests.conftest import make_settings

CONSENT = {"consent": True, "consent_version": "2026-10-13"}


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _count(engine: Engine, tabel: str, **where) -> int:
    kondisi = " AND ".join(f"{k} = :{k}" for k in where) or "TRUE"
    with engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {tabel} WHERE {kondisi}"), where).scalar()


def _buat(client: TestClient) -> dict:
    r = client.post("/api/v1/session", json=CONSENT)
    assert r.status_code == 201, r.text
    return r.json()


# ---------- unit: token dan limiter (tanpa DB) ----------


def test_token_acak_256_bit_dan_hash():
    a, b = buat_token(), buat_token()
    assert a != b
    assert len(a) >= 43  # 32 byte url-safe base64 = 43 karakter
    assert hash_token(a) == hash_token(a) != a
    assert len(hash_token(a)) == 64


def test_limiter_jendela_geser():
    t = [100.0]
    lim = SlidingWindowLimiter(clock=lambda: t[0])
    batas = Batas(maks=2, jendela_detik=10)
    assert lim.periksa("k", batas) is None
    assert lim.periksa("k", batas) is None
    tunggu = lim.periksa("k", batas)
    assert tunggu is not None and 9 < tunggu <= 10
    assert lim.periksa("lain", batas) is None  # kunci lain tidak terpengaruh
    t[0] += 10.5
    assert lim.periksa("k", batas) is None  # jendela bergeser, kuota pulih
    t[0] += 100
    assert lim.sweep() >= 1


def _req(client_host: str, xff: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": headers, "client": (client_host, 5000)})


def test_ip_klien_abaikan_xff_dari_sumber_tak_tepercaya():
    # Penyerang mengirim XFF palsu langsung ke API: tidak boleh dipercaya.
    assert ip_klien(_req("203.0.113.9", "1.2.3.4"), []) == "203.0.113.9"
    assert ip_klien(_req("203.0.113.9", "1.2.3.4"), ["172.16.0.0/12"]) == "203.0.113.9"


def test_ip_klien_pakai_xff_dari_proxy_tepercaya():
    proxy = ["172.16.0.0/12"]
    assert ip_klien(_req("172.18.0.2", "198.51.100.7"), proxy) == "198.51.100.7"
    # XFF rantai: klien palsu di kiri diabaikan, ambil entri tak tepercaya terkanan
    assert (
        ip_klien(_req("172.18.0.2", "6.6.6.6, 198.51.100.7, 172.18.0.5"), proxy) == "198.51.100.7"
    )
    assert ip_klien(_req("172.18.0.2"), proxy) == "172.18.0.2"  # tanpa header


# ---------- API: kriteria penerimaan 7.1 ----------


@pytest.mark.db
class TestSesiAPI:
    def test_tanpa_consent_ditolak_dan_tidak_ada_baris(self, client: TestClient, clean_db: Engine):
        for body in ({}, {"consent": False, "consent_version": "v1"}, {"consent_version": "v1"}):
            r = client.post("/api/v1/session", json=body)
            assert r.status_code == 400, body
            assert r.json()["error"]["kode"] == "consent_diperlukan"
        assert _count(clean_db, "sessions") == 0

    def test_consent_tanpa_versi_ditolak_422(self, client: TestClient, clean_db: Engine):
        r = client.post("/api/v1/session", json={"consent": True})
        assert r.status_code == 422
        assert r.json()["error"]["detail"]["field"][0]["field"] == "consent_version"
        assert _count(clean_db, "sessions") == 0

    def test_field_tak_dikenal_ditolak(self, client: TestClient):
        r = client.post("/api/v1/session", json={**CONSENT, "email": "a@b.c"})
        assert r.status_code == 422

    def test_buat_sesi_dan_hanya_hash_disimpan(self, client: TestClient, clean_db: Engine):
        data = _buat(client)
        assert set(data) == {"token", "expires_at", "sisa_detik", "pemberitahuan"}
        assert "data fiktif" in data["pemberitahuan"]  # catatan demo untuk UI
        assert 86390 <= data["sisa_detik"] <= 86400
        with Session(clean_db) as s:
            baris = s.query(Sesi).one()
            assert baris.token_hash == hash_token(data["token"])
            assert baris.token_hash != data["token"]
            assert baris.consent_version == "2026-10-13"
            assert baris.consent_at is not None

    def test_status_sesi(self, client: TestClient):
        token = _buat(client)["token"]
        r = client.get("/api/v1/session", headers=_auth(token))
        assert r.status_code == 200
        body = r.json()
        assert body["aktif"] is True and 0 < body["sisa_detik"] <= 86400

    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {"Authorization": "Bearer salah"},
            {"Authorization": "Basic abc"},
            {"Authorization": "Bearer"},
        ],
    )
    def test_token_tidak_valid_401(self, client: TestClient, headers):
        r = client.get("/api/v1/session", headers=headers)
        assert r.status_code == 401
        assert r.json()["error"]["kode"] == "token_tidak_valid"
        assert r.headers["www-authenticate"] == "Bearer"

    def test_token_kedaluwarsa_401(self, client: TestClient, clean_db: Engine):
        token = _buat(client)["token"]
        with Session(clean_db) as s:
            s.query(Sesi).update({"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
            s.commit()
        assert client.get("/api/v1/session", headers=_auth(token)).status_code == 401

    def test_health_tanpa_token(self, client: TestClient):
        assert client.get("/api/v1/health").status_code == 200

    def test_delete_menghapus_sesi_dan_semua_data_turunan(
        self, client: TestClient, clean_db: Engine
    ):
        token = _buat(client)["token"]
        with Session(clean_db) as s:
            sid = s.query(Sesi).one().id
            s.add(Profil(session_id=sid, tahun_lulus=2026))
            s.add(Strategi(session_id=sid, jalur="SNBT", pilihan=[], hasil_evaluasi={}))
            s.add(QueryLog(session_id=sid, pertanyaan="uji", yakin=True, sumber_ids=[]))
            s.commit()

        r = client.delete("/api/v1/session", headers=_auth(token))
        assert r.status_code == 204
        for tabel in ("sessions",):
            assert _count(clean_db, tabel) == 0
        for tabel in ("profiles", "strategies", "query_logs"):
            assert _count(clean_db, tabel, session_id=sid) == 0
        assert client.get("/api/v1/session", headers=_auth(token)).status_code == 401

    def test_delete_hanya_menghapus_sesi_sendiri(self, client: TestClient, clean_db: Engine):
        a, b = _buat(client)["token"], _buat(client)["token"]
        assert client.delete("/api/v1/session", headers=_auth(a)).status_code == 204
        assert client.get("/api/v1/session", headers=_auth(b)).status_code == 200

    def test_ttl_dari_env_menimpa_config(self, clean_db: Engine, app_config: AppConfig):
        app = create_app(make_settings(session_ttl_hours=2), app_config, clean_db)
        with TestClient(app) as c:
            assert 7190 <= _buat(c)["sisa_detik"] <= 7200

    def test_pembersihan_menghapus_hanya_yang_kedaluwarsa(self, clean_db: Engine):
        factory = sessionmaker(bind=clean_db, expire_on_commit=False)
        sekarang = datetime.now(UTC)
        with factory() as s:
            for nama, delta in (("lama", -1), ("baru", 1)):
                s.add(
                    Sesi(
                        id=uuid.uuid4(),
                        token_hash=hash_token(nama),
                        consent_at=sekarang,
                        consent_version="v1",
                        expires_at=sekarang + timedelta(hours=delta),
                    )
                )
            s.commit()
        assert hapus_kedaluwarsa(factory) == 1
        assert _count(clean_db, "sessions") == 1
        assert _count(clean_db, "sessions", token_hash=hash_token("baru")) == 1


@pytest.mark.db
class TestRateLimit:
    def _client(self, clean_db: Engine, app_config: AppConfig, **batas) -> TestClient:
        rl = app_config.rate_limit.model_copy(update=batas)
        cfg = app_config.model_copy(update={"rate_limit": rl})
        return TestClient(create_app(make_settings(), cfg, clean_db))

    def test_buat_sesi_dibatasi_per_ip_dengan_retry_after(
        self, clean_db: Engine, app_config: AppConfig
    ):
        c = self._client(clean_db, app_config, buat_sesi_per_ip=Batas(maks=2, jendela_detik=60))
        assert c.post("/api/v1/session", json=CONSENT).status_code == 201
        assert c.post("/api/v1/session", json=CONSENT).status_code == 201
        r = c.post("/api/v1/session", json=CONSENT)
        assert r.status_code == 429
        assert r.json()["error"]["kode"] == "terlalu_banyak_permintaan"
        assert 1 <= int(r.headers["retry-after"]) <= 60

    def test_endpoint_terautentikasi_dibatasi_per_sesi(
        self, clean_db: Engine, app_config: AppConfig
    ):
        c = self._client(clean_db, app_config, per_sesi=Batas(maks=3, jendela_detik=60))
        token = _buat(c)["token"]
        kode = [c.get("/api/v1/session", headers=_auth(token)).status_code for _ in range(4)]
        assert kode == [200, 200, 200, 429]
        # sesi lain tidak ikut terblokir
        lain = _buat(c)["token"]
        assert c.get("/api/v1/session", headers=_auth(lain)).status_code == 200

    def test_percobaan_token_salah_dibatasi_per_ip(self, clean_db: Engine, app_config: AppConfig):
        c = self._client(clean_db, app_config, per_ip=Batas(maks=2, jendela_detik=60))
        kode = [c.get("/api/v1/session", headers=_auth("tebakan")).status_code for _ in range(3)]
        assert kode == [401, 401, 429]
