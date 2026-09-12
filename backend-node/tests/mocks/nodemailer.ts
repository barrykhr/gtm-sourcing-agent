// Fake nodemailer transport -- notifications.ts's isConfigured() gate
// stays real (tests set real SMTP_* env vars so it reports true); only
// the actual network send is faked, captured here for assertions.
export const sentEmails: Array<{ from: string; to: string; subject: string; text: string }> = [];

export default {
  createTransport: () => ({
    sendMail: async (opts: { from: string; to: string; subject: string; text: string }) => {
      sentEmails.push(opts);
      return { messageId: `fake-${sentEmails.length}` };
    },
  }),
};
