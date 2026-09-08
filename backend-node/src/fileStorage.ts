// Port of file_storage.py -- S3-compatible object storage for the
// original uploaded resume file, purely additive (resumeExtraction.ts
// and candidateAnalysis.ts don't depend on this at all). Configured
// entirely through env vars so any S3-compatible provider works
// (Cloudflare R2 recommended). Never fakes success: if the required env
// vars aren't set, every function here is a no-op that returns null.
import crypto from "node:crypto";
import { S3Client, PutObjectCommand, GetObjectCommand } from "@aws-sdk/client-s3";
import { getSignedUrl } from "@aws-sdk/s3-request-presigner";

const ENV_ENDPOINT_URL = "RESUME_STORAGE_ENDPOINT_URL";
const ENV_BUCKET = "RESUME_STORAGE_BUCKET";
const ENV_ACCESS_KEY_ID = "RESUME_STORAGE_ACCESS_KEY_ID";
const ENV_SECRET_ACCESS_KEY = "RESUME_STORAGE_SECRET_ACCESS_KEY";
const ENV_REGION = "RESUME_STORAGE_REGION"; // optional -- R2 ignores it, but the SDK requires some value

export function isConfigured(): boolean {
  return Boolean(process.env[ENV_BUCKET] && process.env[ENV_ACCESS_KEY_ID] && process.env[ENV_SECRET_ACCESS_KEY]);
}

let cachedClient: S3Client | null = null;
let cachedKey: string | null = null;

function getClient(): S3Client {
  const key = `${process.env[ENV_ENDPOINT_URL] ?? ""}|${process.env[ENV_ACCESS_KEY_ID]}|${process.env[ENV_SECRET_ACCESS_KEY]}`;
  if (cachedClient === null || key !== cachedKey) {
    cachedClient = new S3Client({
      endpoint: process.env[ENV_ENDPOINT_URL] || undefined,
      region: process.env[ENV_REGION] || "auto",
      credentials: {
        accessKeyId: process.env[ENV_ACCESS_KEY_ID]!,
        secretAccessKey: process.env[ENV_SECRET_ACCESS_KEY]!,
      },
      forcePathStyle: true,
    });
    cachedKey = key;
  }
  return cachedClient;
}

/** Uploads the original resume file. Namespaced by roleId rather than a
 * candidate id -- this runs before the async add_candidate task has
 * created the candidate, so no candidate id exists yet. Returns the
 * storage key on success, or null if storage isn't configured --
 * callers must treat null as "not persisted, and that's fine". */
export async function uploadResume(
  roleId: string, filename: string, content: Buffer, contentType: string
): Promise<string | null> {
  if (!isConfigured()) return null;
  const bucket = process.env[ENV_BUCKET]!;
  const key = `resumes/${roleId}/${crypto.randomBytes(6).toString("hex")}-${filename}`;
  try {
    await getClient().send(new PutObjectCommand({ Bucket: bucket, Key: key, Body: content, ContentType: contentType }));
  } catch (e) {
    console.error(`resume upload failed for role ${roleId}`, e);
    return null;
  }
  return key;
}

/** A time-limited presigned URL the recruiter's browser can fetch
 * directly -- this app never proxies the file bytes, and the link is
 * never permanently public. */
export async function getResumeDownloadUrl(fileKey: string, expiresInSeconds = 3600): Promise<string | null> {
  if (!isConfigured()) return null;
  const bucket = process.env[ENV_BUCKET]!;
  try {
    return await getSignedUrl(
      getClient(), new GetObjectCommand({ Bucket: bucket, Key: fileKey }), { expiresIn: expiresInSeconds }
    );
  } catch (e) {
    console.error(`failed to generate a resume download URL for key ${fileKey}`, e);
    return null;
  }
}
