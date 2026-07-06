import { useMutation } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import type { ChangeEvent, FormEvent } from 'react';

import {
  extractRecipeApiRecipesExtractPostMutation,
  uploadRecipeVideoApiRecipesUploadPostMutation,
} from '../client/@tanstack/react-query.gen';
import type { JobOut } from '../client/types.gen';
import { apiErrorMessage } from '../lib/error-message';

interface PasteBarProps {
  /** Called with the job resource (202 new / 200 dedupe hit) — adds a chip. */
  onJob: (job: JobOut) => void;
}

/**
 * The core-loop entry point, pinned at the top of the library: paste a
 * Bilibili/Rednote link and extract, or upload a saved video file (the
 * §16.10 tier-2 floor — extraction must never require platform access).
 */
export function PasteBar({ onJob }: PasteBarProps) {
  const [url, setUrl] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const extract = useMutation(extractRecipeApiRecipesExtractPostMutation());
  const upload = useMutation(uploadRecipeVideoApiRecipesUploadPostMutation());

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = url.trim();
    if (!trimmed || extract.isPending) return;
    extract.mutate(
      { body: { url: trimmed } },
      {
        onSuccess: (job) => {
          onJob(job);
          setUrl('');
        },
      },
    );
  }

  function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || upload.isPending) return;
    upload.mutate(
      { body: { file } },
      {
        onSuccess: (job) => onJob(job),
        onSettled: () => {
          if (fileInputRef.current) fileInputRef.current.value = '';
        },
      },
    );
  }

  const error = extract.error ?? upload.error;

  return (
    <div>
      <form
        onSubmit={handleSubmit}
        aria-label="Extract a recipe"
        className="flex flex-col gap-2 sm:flex-row"
      >
        <label className="sr-only" htmlFor="paste-url">
          Video link
        </label>
        <input
          id="paste-url"
          type="text"
          autoComplete="off"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="Paste a Bilibili or Rednote link"
          className="min-w-0 flex-1 rounded-md border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm text-neutral-100 placeholder:text-neutral-500 focus:border-emerald-500 focus:outline-none"
        />
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={extract.isPending}
            className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {extract.isPending ? 'Submitting…' : 'Extract'}
          </button>
          <input
            ref={fileInputRef}
            id="upload-video"
            type="file"
            accept="video/*"
            aria-label="Upload video file"
            onChange={handleFile}
            className="sr-only"
          />
          <button
            type="button"
            disabled={upload.isPending}
            onClick={() => fileInputRef.current?.click()}
            className="rounded-md border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:border-neutral-500 hover:text-neutral-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {upload.isPending ? 'Uploading…' : 'Upload video'}
          </button>
        </div>
      </form>
      {error != null && (
        <p role="alert" className="mt-2 text-sm text-red-400">
          {apiErrorMessage(error)}
        </p>
      )}
    </div>
  );
}
