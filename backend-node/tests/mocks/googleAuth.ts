// Fake google-auth-library -- auth/service.ts's verifyGoogleIdToken()
// only ever calls new OAuth2Client(...).verifyIdToken({idToken, audience})
// and reads ticket.getPayload(). Rather than faking a real signed JWT,
// tests pass a JSON string (email/email_verified) as the "credential" and
// this fake decodes it directly -- no cryptography needed to exercise the
// real business logic (allowed-domain check, new-vs-returning account).
export class OAuth2Client {
  constructor(_clientId?: string) {}
  async verifyIdToken({ idToken }: { idToken: string; audience?: string }) {
    const payload = JSON.parse(idToken);
    return { getPayload: () => payload };
  }
}
