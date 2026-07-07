import { useMutation } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import type { ChangeEvent, FormEvent } from 'react';

import {
  extractRecipeApiRecipesExtractPostMutation,
  uploadRecipeVideoApiRecipesUploadPostMutation,
} from '../client/@tanstack/react-query.gen';
import type { JobOut } from '../client/types.gen';
import { apiErrorMessage } from '../lib/error-message';
import { STRIP_LIGHT } from './brand/platform-accents';

interface PasteBarProps {
  /** Called with the job resource (202 new / 200 dedupe hit) — adds a chip. */
  onJob: (job: JobOut) => void;
}

/**
 * The core-loop entry point, pinned at the top of the library — direction B's
 * stall front: paste a Bilibili/Rednote link and extract, or upload a saved
 * video file (the §16.10 tier-2 floor — extraction never requires platform
 * access). Button caps are text-transform only so accessible names stay
 * exactly "Extract" / "Upload video".
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
    <div className="relative overflow-hidden rounded-card border border-line-bright bg-panel-deep px-5 pt-5 pb-4">
      <span
        aria-hidden="true"
        className="absolute top-0 right-[8%] left-[8%] h-0.5 opacity-85"
        style={{
          background: STRIP_LIGHT,
          boxShadow:
            '0 2px 18px 1px color-mix(in srgb, var(--color-chili) 25%, transparent)',
        }}
      />
      <p className="glow-text-gold mb-3 font-display text-[11px] font-bold tracking-[0.34em] text-gold uppercase">
        Order up{' '}
        <span lang="zh" className="font-body font-medium tracking-[0.2em]">
          · 点单
        </span>
      </p>
      <form
        onSubmit={handleSubmit}
        aria-label="Extract a recipe"
        className="flex flex-col gap-2.5 sm:flex-row"
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
          className="focus:glow-cyan h-12 min-w-0 flex-1 rounded-field border border-line-bright bg-night px-4 text-[15px] text-ink placeholder:text-ink-faint focus:border-cyan focus:outline-none"
        />
        <div className="flex gap-2.5">
          <button
            type="submit"
            disabled={extract.isPending}
            className="glow-chili glow-text-chili h-12 flex-1 rounded-field border border-chili/80 bg-chili/10 px-6 font-display text-sm font-bold tracking-[0.16em] text-[#ffdbe3] uppercase transition hover:bg-chili/20 disabled:cursor-not-allowed disabled:opacity-50 sm:flex-none"
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
            className="h-12 flex-1 rounded-field border border-line-bright bg-transparent px-5 font-display text-sm font-semibold tracking-[0.16em] text-ink-dim uppercase transition hover:border-cyan/55 hover:text-cyan disabled:cursor-not-allowed disabled:opacity-50 sm:flex-none"
          >
            {upload.isPending ? 'Uploading…' : 'Upload video'}
          </button>
        </div>
      </form>
      <p className="mt-3 text-[12.5px] text-ink-faint">
        chefclaw does the reading so you can do the cooking —{' '}
        <span lang="zh" className="text-[#7d7466]">
          我负责抄，你负责炒。
        </span>
      </p>
      {error != null && (
        <p role="alert" className="mt-2 text-sm text-chili-bright">
          {apiErrorMessage(error)}
        </p>
      )}
    </div>
  );
}
