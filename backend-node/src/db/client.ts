// Prisma client singleton. Points at the same DATABASE_URL the Python
// backend uses — see prisma/schema.prisma's header comment. No engine
// pooling tuning here yet (db.py's Postgres pool_size/max_overflow/
// pool_recycle settings are a Phase 4+ port item, not needed for the
// auth-only slice this file currently backs).
import { PrismaClient } from "@prisma/client";

export const prisma = new PrismaClient();
