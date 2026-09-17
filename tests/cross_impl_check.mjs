// Invoked by test_cross_impl.py as a subprocess. Takes one JSON-encoded
// argv describing a single prediction call, runs it through the published
// @urology-ai/epsa-engine port of this repo's model, and prints the JSON
// result to stdout — so Python can diff it against model.predict()'s own
// output for the identical inputs.
import { predictBiopsyRisk } from '@urology-ai/epsa-engine';

const input = JSON.parse(process.argv[2]);
const result = predictBiopsyRisk(
  input.pirads,
  input.psa,
  input.prostate_volume_cc ?? null,
  input.psad ?? null
);
process.stdout.write(JSON.stringify(result));
