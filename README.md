# Data Governance Platform — Local Docker Infrastructure

Stack local gồm PostgreSQL, OpenSearch, OpenMetadata 1.13.1, OpenMetadata external ingestion, Apache Ranger 2.8.0 và Trino 482.

## Khởi tạo lần đầu

Khởi động Ranger trước:

```bash
docker compose up -d ranger-db ranger-solr ranger-admin
```

Chờ Ranger Admin healthy rồi chạy bootstrap thủ công:

```bash
./scripts/bootstrap-ranger.sh
```

Sau đó khởi động toàn bộ stack:

```bash
docker compose up -d
```

`bootstrap-ranger.sh` chạy trên host bằng `python3` và chỉ dùng thư viện chuẩn Python, không kéo image `python:3.12-alpine`.
Script idempotent nên có thể chạy lại. Nó chỉ tạo những thành phần còn thiếu:

- Ranger service `dev_trino`;
- quyền dữ liệu toàn bộ cho `admin`;
- quyền execute query cho các user local;
- quyền self-impersonation cần cho Trino.

Policy được lưu trong volume `ranger_db_data`. Restart Ranger không cần chạy lại bootstrap.

## Các cổng local

- OpenMetadata: http://localhost:8585
- Ranger Admin: http://localhost:6080
- Trino: http://127.0.0.1:8080
- PostgreSQL nghiệp vụ/OpenMetadata: `127.0.0.1:5432`
- Ranger PostgreSQL: `127.0.0.1:5433`

Kết nối Ranger DB từ host:

```bash
psql -h 127.0.0.1 -p 5433 -U rangeradmin
```

Port Ranger DB có thể đổi trong `.env`:

```dotenv
RANGER_DB_HOST_PORT=5433
```

## OpenMetadata ingestion Bot token

Service ingestion chỉ dùng `OM_INGESTION_BOT_TOKEN`, không fallback sang admin password hoặc PAT.
Token phải thuộc đúng OpenMetadata instance đang chạy:

```dotenv
OM_INGESTION_BOT_TOKEN=eyJ...
```

Sau khi đổi token:

```bash
docker compose up -d --force-recreate metadata-ingestion
```

## Kiểm tra

```bash
docker compose ps -a
docker compose logs --tail=200 ranger-admin
docker compose logs --tail=200 trino
docker compose logs --tail=200 metadata-ingestion

docker exec governance-trino trino --user analyst --execute 'SHOW CATALOGS'
```
