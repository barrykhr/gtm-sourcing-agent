// One-off seed for the scratch Postgres DB used in the manual/E2E
// verification pass -- creates a single admin account so Playwright can
// exercise a real login, not a signup. Run with DATABASE_URL pointed at
// the scratch database.
import * as auth from "../src/auth/service.js";

const email = "scratch-admin@talyn.test";
const password = "scratch-admin-pw-1";

const user = await auth.createUser(email, password);
console.log(`seeded ${user.role} account: ${email} / ${password}`);
process.exit(0);
