# Object storage: MinIO, AWS S3, or R2

Aptil stores uploaded CVs and generated résumés in an S3-compatible bucket.
`app/services/storage.py` uses boto3 against a configurable `endpoint_url`, so
the same four settings point at MinIO, AWS S3, Cloudflare R2, or Backblaze B2.

The variables are still named `MINIO_*` for historical reasons. Read them as
generic S3 settings:

| Variable | Means |
|---|---|
| `MINIO_ENDPOINT` | Host only, no scheme. **Leave empty for real AWS S3.** |
| `MINIO_ROOT_USER` | Access Key ID |
| `MINIO_ROOT_PASSWORD` | Secret Access Key |
| `MINIO_BUCKET` | Bucket name |
| `MINIO_SECURE` | `true` for HTTPS (any cloud provider), `false` for local MinIO |
| `MINIO_REGION` | Part of the SigV4 signature. Wrong value ⇒ `SignatureDoesNotMatch` |

## Option A — MinIO (local dev and single-VPS production)

This is what `docker-compose.yml` runs. `MINIO_ROOT_PASSWORD` is passed to *both*
the MinIO container (as its root password) and the API (as its secret key), so
one value configures both sides — they cannot drift.

Invent a strong one; it is not issued by anyone:

```bash
python -c "import secrets,string; print(''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(40)))"
```

```
MINIO_ENDPOINT=minio:9000
MINIO_ROOT_USER=aptil
MINIO_ROOT_PASSWORD=<the generated value>
MINIO_BUCKET=aptil-uploads
MINIO_SECURE=false
MINIO_REGION=us-east-1
```

MinIO requires at least 8 characters. Keep it alphanumeric — the value goes into
`.env` unquoted, so `$`, backticks and quotes will bite you.

## Option B — AWS S3

Better than MinIO if you already have AWS, and required if you deploy somewhere
with no persistent disk (Render, Fly, etc.).

**1. Create the bucket** — private, block all public access (the app hands out
short-lived presigned URLs, so nothing needs to be public).

```bash
aws s3api create-bucket --bucket aptil-uploads-CHANGEME \
  --region eu-west-1 --create-bucket-configuration LocationConstraint=eu-west-1
aws s3api put-public-access-block --bucket aptil-uploads-CHANGEME \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
```

Bucket names are globally unique, so pick something with a suffix.

**2. Create a scoped IAM user** — do *not* use your root keys. This policy grants
only what the app actually calls (`head_bucket`, `create_bucket`, `put_object`,
`get_object`, `delete_object`, and presigning):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BucketLevel",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::aptil-uploads-CHANGEME"
    },
    {
      "Sid": "ObjectLevel",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::aptil-uploads-CHANGEME/*"
    }
  ]
}
```

Note this policy deliberately omits `s3:CreateBucket`. `ensure_bucket()` calls
`head_bucket` first and returns quietly when the bucket already exists, so
pre-creating it in step 1 means the app never needs create permission.

**3. Configure.** Leave `MINIO_ENDPOINT` **empty** so boto3 uses the region's
default AWS endpoint:

```
MINIO_ENDPOINT=
MINIO_ROOT_USER=AKIA...            # the IAM user's Access Key ID
MINIO_ROOT_PASSWORD=...            # its Secret Access Key
MINIO_BUCKET=aptil-uploads-CHANGEME
MINIO_SECURE=true
MINIO_REGION=eu-west-1             # MUST match the bucket's region
```

The region matters. It is part of the SigV4 signature, so a mismatch fails with
`SignatureDoesNotMatch` rather than a helpful error.

If you'd rather pin an explicit endpoint, `s3.eu-west-1.amazonaws.com` works too
— just keep it consistent with `MINIO_REGION`.

**4. Also comment out the `minio` service** in `docker-compose.yml`, or leave it
running and unused. Nothing else changes.

## Option C — Cloudflare R2

Same shape as S3, with an account-specific endpoint and a fixed region of `auto`:

```
MINIO_ENDPOINT=<account-id>.r2.cloudflarestorage.com
MINIO_ROOT_USER=<R2 access key id>
MINIO_ROOT_PASSWORD=<R2 secret access key>
MINIO_BUCKET=aptil-uploads
MINIO_SECURE=true
MINIO_REGION=auto
```

R2 has no egress fees, which is the main reason to prefer it over S3 for a
CV-heavy workload.

## Verifying whichever you chose

```bash
cd backend
python -c "
from app.services import storage
storage.ensure_bucket()
k = storage.upload_bytes(b'hello', 'healthcheck/probe.txt', 'text/plain')
assert storage.download_bytes(k) == b'hello'
print('presigned:', storage.presigned_get_url(k, 60).split('?')[0])
storage.delete_object(k)
print('OK — storage is wired up correctly')
"
```

A `SignatureDoesNotMatch` here almost always means `MINIO_REGION` doesn't match
the bucket. `AccessDenied` on the first call usually means the IAM policy is
missing `s3:ListBucket` at the bucket level (needed by `head_bucket`).
