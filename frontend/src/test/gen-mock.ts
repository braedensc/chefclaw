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
  AdminSpendOut,
  HealthResponse,
  InviteOut,
  InvitePublicOut,
  JobOut,
  MeOut,
  RecipeDetail,
  RecipePage,
  SpendSummaryOut,
  UserAdminRow,
} from '../client/types.gen';
import {
  adminSpendSummary,
  healthResponse,
  invitePublic,
  meOut,
  recipePage,
  spendSummary,
} from './fixtures';

/** A mocked generated mutationFn — tests assert on the options it receives. */
type MutationMock = Mock<(options: unknown) => unknown>;

const mutationMock = () => vi.fn<(options: unknown) => unknown>();

interface GenState {
  /** GET /api/me — the authenticated identity (AuthGate). */
  me: MeOut;
  /** When set, the me queryFn throws it (401/unauthenticated scenarios). */
  meError: Error | null;
  /** GET /api/admin/invites list. */
  invitesList: InviteOut[];
  /** When set, the invites-list queryFn throws it. */
  invitesError: Error | null;
  /** GET /api/invites/{token} — the public invite-accept shape. */
  publicInviteResult: InvitePublicOut;
  /** When set, the public-invite queryFn throws it. */
  publicInviteError: Error | null;
  logout: MutationMock;
  createInvite: MutationMock;
  revokeInvite: MutationMock;
  /** GET /api/admin/users — members + their real-frame grant (V2-F). */
  usersList: UserAdminRow[];
  /** When set, the users-list queryFn throws it. */
  usersError: Error | null;
  setRealCovers: MutationMock;
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
  /** GET /api/admin/spend — the cross-user rollup (admin page). */
  adminSpend: AdminSpendOut;
  /** When set, the admin-spend queryFn throws it instead. */
  adminSpendError: Error | null;
  extract: MutationMock;
  upload: MutationMock;
  patch: MutationMock;
  deleteRecipe: MutationMock;
  /** POST /api/recipes/{id}/illustration — regenerate/retry a cover job. */
  regenerateIllustration: MutationMock;
  /**
   * CoverImage's blob fetch — resolve with a Blob to show the illustration;
   * the default (resolving undefined) errors the query, so images fall back
   * to the platform tile unless a test opts in.
   */
  image: MutationMock;
}

export const genState: GenState = {
  me: meOut(),
  meError: null,
  invitesList: [],
  invitesError: null,
  publicInviteResult: invitePublic(),
  publicInviteError: null,
  logout: mutationMock(),
  createInvite: mutationMock(),
  revokeInvite: mutationMock(),
  usersList: [],
  usersError: null,
  setRealCovers: mutationMock(),
  recipesPage: recipePage([]),
  recipesById: {},
  jobsById: {},
  jobsList: [],
  health: healthResponse(),
  healthError: null,
  spend: spendSummary(),
  spendError: null,
  adminSpend: adminSpendSummary(),
  adminSpendError: null,
  extract: mutationMock(),
  upload: mutationMock(),
  patch: mutationMock(),
  deleteRecipe: mutationMock(),
  regenerateIllustration: mutationMock(),
  image: mutationMock(),
};

export function resetGenState(): void {
  genState.me = meOut();
  genState.meError = null;
  genState.invitesList = [];
  genState.invitesError = null;
  genState.publicInviteResult = invitePublic();
  genState.publicInviteError = null;
  genState.logout = mutationMock();
  genState.createInvite = mutationMock();
  genState.revokeInvite = mutationMock();
  genState.recipesPage = recipePage([]);
  genState.recipesById = {};
  genState.jobsById = {};
  genState.jobsList = [];
  genState.health = healthResponse();
  genState.healthError = null;
  genState.spend = spendSummary();
  genState.spendError = null;
  genState.adminSpend = adminSpendSummary();
  genState.adminSpendError = null;
  genState.extract = mutationMock();
  genState.upload = mutationMock();
  genState.patch = mutationMock();
  genState.deleteRecipe = mutationMock();
  genState.regenerateIllustration = mutationMock();
  genState.image = mutationMock();
}

/** The `_id` discriminators match the real generated module's createQueryKey. */
export function genMockModule() {
  return {
    // ── M2 auth + invites ──────────────────────────────────────────────────
    meApiMeGetQueryKey: () => [{ _id: 'meApiMeGet' }],
    meApiMeGetOptions: () => ({
      queryKey: [{ _id: 'meApiMeGet' }],
      queryFn: async () => {
        if (genState.meError) throw genState.meError;
        return genState.me;
      },
    }),
    logoutApiAuthLogoutPostMutation: () => ({
      mutationFn: (options: unknown) => genState.logout(options),
    }),
    listInvitesApiAdminInvitesGetQueryKey: () => [
      { _id: 'listInvitesApiAdminInvitesGet' },
    ],
    listInvitesApiAdminInvitesGetOptions: () => ({
      queryKey: [{ _id: 'listInvitesApiAdminInvitesGet' }],
      queryFn: async () => {
        if (genState.invitesError) throw genState.invitesError;
        return { items: genState.invitesList };
      },
    }),
    createInviteApiAdminInvitesPostMutation: () => ({
      mutationFn: (options: unknown) => genState.createInvite(options),
    }),
    revokeInviteApiAdminInvitesInviteIdRevokePostMutation: () => ({
      mutationFn: (options: unknown) => genState.revokeInvite(options),
    }),
    listUsersApiAdminUsersGetQueryKey: () => [
      { _id: 'listUsersApiAdminUsersGet' },
    ],
    listUsersApiAdminUsersGetOptions: () => ({
      queryKey: [{ _id: 'listUsersApiAdminUsersGet' }],
      queryFn: async () => {
        if (genState.usersError) throw genState.usersError;
        return { items: genState.usersList };
      },
    }),
    setUserRealCoversApiAdminUsersUserIdPatchMutation: () => ({
      mutationFn: (options: unknown) => genState.setRealCovers(options),
    }),
    publicInviteApiInvitesTokenGetOptions: (options: {
      path: { token: string };
    }) => ({
      queryKey: [{ _id: 'publicInviteApiInvitesTokenGet', path: options.path }],
      queryFn: async () => {
        if (genState.publicInviteError) throw genState.publicInviteError;
        return genState.publicInviteResult;
      },
    }),

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

    getRecipeImageApiRecipesRecipeIdImageGetQueryKey: (options: {
      path: { recipe_id: string };
    }) => [
      { _id: 'getRecipeImageApiRecipesRecipeIdImageGet', path: options.path },
    ],
    getRecipeImageApiRecipesRecipeIdImageGetOptions: (options: {
      path: { recipe_id: string };
    }) => ({
      queryKey: [
        { _id: 'getRecipeImageApiRecipesRecipeIdImageGet', path: options.path },
      ],
      queryFn: async () => {
        const image = await genState.image(options);
        if (image === undefined) {
          throw new Error(`gen-mock: no image for ${options.path.recipe_id}`);
        }
        return image;
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
    regenerateIllustrationApiRecipesRecipeIdIllustrationPostMutation: () => ({
      mutationFn: (options: unknown) =>
        genState.regenerateIllustration(options),
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

    // admin-invites-page.tsx spend rollup — genState.adminSpendError fails it.
    adminSpendApiAdminSpendGetOptions: () => ({
      queryKey: [{ _id: 'adminSpendApiAdminSpendGet' }],
      queryFn: async () => {
        if (genState.adminSpendError) throw genState.adminSpendError;
        return genState.adminSpend;
      },
    }),
  };
}
