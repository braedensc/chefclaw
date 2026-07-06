// Shared mock for the generated query-options module
// (src/client/@tanstack/react-query.gen) — component tests never real-fetch.
//
// Usage in a test file:
//
//   vi.mock('../client/@tanstack/react-query.gen', async () =>
//     (await import('../test/gen-mock')).genMockModule(),
//   );
//
// then drive scenarios by assigning to `genState` (and call resetGenState()
// in beforeEach). Query functions read genState lazily, so a test can change
// the canned data mid-test (e.g. the recipes list gaining a card before an
// invalidation-triggered refetch).

import { vi } from 'vitest';
import type { Mock } from 'vitest';

import type {
  HealthResponse,
  JobOut,
  RecipeDetail,
  RecipePage,
  SpendSummaryOut,
} from '../client/types.gen';
import { healthResponse, recipePage, spendSummary } from './fixtures';

/** A mocked generated mutationFn — tests assert on the options it receives. */
type MutationMock = Mock<(options: unknown) => unknown>;

const mutationMock = () => vi.fn<(options: unknown) => unknown>();

interface GenState {
  recipesPage: RecipePage;
  recipesById: Record<string, RecipeDetail>;
  jobsById: Record<string, JobOut>;
  jobsList: JobOut[];
  health: HealthResponse;
  /** When set, the health queryFn throws it instead (401/network scenarios). */
  healthError: Error | null;
  spend: SpendSummaryOut;
  /** When set, the spend queryFn throws it instead. */
  spendError: Error | null;
  extract: MutationMock;
  upload: MutationMock;
  patch: MutationMock;
  deleteRecipe: MutationMock;
}

export const genState: GenState = {
  recipesPage: recipePage([]),
  recipesById: {},
  jobsById: {},
  jobsList: [],
  health: healthResponse(),
  healthError: null,
  spend: spendSummary(),
  spendError: null,
  extract: mutationMock(),
  upload: mutationMock(),
  patch: mutationMock(),
  deleteRecipe: mutationMock(),
};

export function resetGenState(): void {
  genState.recipesPage = recipePage([]);
  genState.recipesById = {};
  genState.jobsById = {};
  genState.jobsList = [];
  genState.health = healthResponse();
  genState.healthError = null;
  genState.spend = spendSummary();
  genState.spendError = null;
  genState.extract = mutationMock();
  genState.upload = mutationMock();
  genState.patch = mutationMock();
  genState.deleteRecipe = mutationMock();
}

/** The `_id` discriminators match the real generated module's createQueryKey. */
export function genMockModule() {
  return {
    listRecipesApiRecipesGetQueryKey: () => [
      { _id: 'listRecipesApiRecipesGet' },
    ],
    listRecipesApiRecipesGetOptions: (options?: { query?: unknown }) => ({
      queryKey: [{ _id: 'listRecipesApiRecipesGet', query: options?.query }],
      queryFn: async () => genState.recipesPage,
    }),

    listJobsApiJobsGetQueryKey: () => [{ _id: 'listJobsApiJobsGet' }],
    listJobsApiJobsGetOptions: () => ({
      queryKey: [{ _id: 'listJobsApiJobsGet' }],
      queryFn: async () => genState.jobsList,
    }),

    getJobApiJobsJobIdGetQueryKey: (options: { path: { job_id: string } }) => [
      { _id: 'getJobApiJobsJobIdGet', path: options.path },
    ],
    getJobApiJobsJobIdGetOptions: (options: { path: { job_id: string } }) => ({
      queryKey: [{ _id: 'getJobApiJobsJobIdGet', path: options.path }],
      queryFn: async () => {
        const job = genState.jobsById[options.path.job_id];
        if (!job) throw new Error(`gen-mock: no job ${options.path.job_id}`);
        return job;
      },
    }),

    getRecipeApiRecipesRecipeIdGetQueryKey: (options: {
      path: { recipe_id: string };
    }) => [{ _id: 'getRecipeApiRecipesRecipeIdGet', path: options.path }],
    getRecipeApiRecipesRecipeIdGetOptions: (options: {
      path: { recipe_id: string };
    }) => ({
      queryKey: [{ _id: 'getRecipeApiRecipesRecipeIdGet', path: options.path }],
      queryFn: async () => {
        const recipe = genState.recipesById[options.path.recipe_id];
        if (!recipe) {
          throw new Error(`gen-mock: no recipe ${options.path.recipe_id}`);
        }
        return recipe;
      },
    }),

    extractRecipeApiRecipesExtractPostMutation: () => ({
      mutationFn: (options: unknown) => genState.extract(options),
    }),
    uploadRecipeVideoApiRecipesUploadPostMutation: () => ({
      mutationFn: (options: unknown) => genState.upload(options),
    }),
    patchRecipeApiRecipesRecipeIdPatchMutation: () => ({
      mutationFn: (options: unknown) => genState.patch(options),
    }),
    deleteRecipeApiRecipesRecipeIdDeleteMutation: () => ({
      mutationFn: (options: unknown) => genState.deleteRecipe(options),
    }),

    // settings-page.tsx (screen 4) — genState.healthError drives failures.
    healthApiHealthGetOptions: () => ({
      queryKey: [{ _id: 'healthApiHealthGet' }],
      queryFn: async () => {
        if (genState.healthError) throw genState.healthError;
        return genState.health;
      },
    }),

    // settings-page.tsx spend history — genState.spendError drives failures.
    getSpendApiSpendGetOptions: (options?: { query?: unknown }) => ({
      queryKey: [{ _id: 'getSpendApiSpendGet', query: options?.query }],
      queryFn: async () => {
        if (genState.spendError) throw genState.spendError;
        return genState.spend;
      },
    }),
  };
}
