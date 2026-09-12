// Fake @aws-sdk/client-s3 + @aws-sdk/s3-request-presigner -- fileStorage.ts's
// isConfigured() gate stays real (tests set real RESUME_STORAGE_* env
// vars); only the actual network calls are faked, captured here for
// assertions.
export const s3Puts: Array<{ bucket: string; key: string; contentType?: string; bodyLength: number }> = [];

export class PutObjectCommand {
  input: any;
  constructor(input: any) {
    this.input = input;
  }
}

export class GetObjectCommand {
  input: any;
  constructor(input: any) {
    this.input = input;
  }
}

export class S3Client {
  constructor(_config: any) {}
  async send(command: PutObjectCommand | GetObjectCommand) {
    if (command instanceof PutObjectCommand) {
      s3Puts.push({
        bucket: command.input.Bucket,
        key: command.input.Key,
        contentType: command.input.ContentType,
        bodyLength: command.input.Body?.length ?? 0,
      });
      return {};
    }
    return {};
  }
}

export async function getSignedUrl(_client: S3Client, command: GetObjectCommand, options: { expiresIn: number }) {
  return `https://fake-signed-url.test/${command.input.Bucket}/${command.input.Key}?expires=${options.expiresIn}`;
}
