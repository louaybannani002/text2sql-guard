/**
 * zod, configured for the strict CSP: by default zod v4 probes `new Function` (an eval) to
 * JIT-compile object parsers, which the CSP blocks and reports. `jitless` must be set before
 * any schema is defined, so every schema imports `z` from here.
 */
import { z } from "zod";

z.config({ jitless: true });

export { z };
