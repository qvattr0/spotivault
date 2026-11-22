import { ChoiceCard, ChoiceCardGroup, Disclosure } from '@/components/ui-c';
import { FORMAT_CHOICES, NO_BENEFIT, type FormatChoiceId } from '@/lib/formats.ts';

interface FormatChoiceProps {
  value: FormatChoiceId;
  onChange: (value: FormatChoiceId) => void;
}

/**
 * Step 6's format cards (web-ui.md § 6; Mj5zE): AAC 256 (default), AAC 320, MP3 320, and FLAC and
 * WAV under a collapsed "More formats", each marked "No benefit". It opens by itself when FLAC or
 * WAV is the saved choice.
 */
export function FormatChoice({ value, onChange }: FormatChoiceProps) {
  const more = FORMAT_CHOICES.some((c) => c.more && c.id === value);
  return (
    <>
      <ChoiceCardGroup label="Format" size="compact" value={value} onChange={onChange}>
        {FORMAT_CHOICES.filter((c) => !c.more).map((c) => (
          <ChoiceCard
            key={c.id}
            value={c.id}
            title={c.label}
            description={c.id === 'aac256' ? `Default · .${c.extension}` : `.${c.extension}`}
          />
        ))}
      </ChoiceCardGroup>
      <Disclosure label="More formats" hint="FLAC, WAV · no benefit, the source is lossy" open={more ? true : undefined}>
        <ChoiceCardGroup label="More formats" size="compact" value={value} onChange={onChange}>
          {FORMAT_CHOICES.filter((c) => c.more).map((c) => (
            <ChoiceCard key={c.id} value={c.id} title={c.label} description={`.${c.extension} · ${NO_BENEFIT}`} />
          ))}
        </ChoiceCardGroup>
      </Disclosure>
    </>
  );
}
