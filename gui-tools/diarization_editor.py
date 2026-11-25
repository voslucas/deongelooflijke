"""Native Python GUI: python gui-tools/diarization_editor.py [--episode 327]."""
import argparse
import json
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
import wave

from diarization_core import EditorSession, ROOT, audio_clip
from utils import ep_key
from voice_utils import SAMPLING_RATE, download_mp3, load_audio


def timestamp(value):
    try:
        seconds = float(value)
        hours, rest = divmod(seconds, 3600)
        minutes, rest = divmod(rest, 60)
        return f'{int(hours):02}:{int(minutes):02}:{rest:05.2f}'
    except (TypeError, ValueError, OverflowError):
        return '?'


class DiarizationEditor(tk.Tk):
    PAGE_SIZE = 30

    def __init__(self, episode=None):
        super().__init__()
        self.title('De Ongelooflijke Podcast — diarization editor')
        self.geometry('1250x850')
        self.minsize(850, 550)
        self.session = None
        self.audio = None
        self.encoder = None
        self.preprocess = None
        self.busy = False
        self.page = 0
        self.messages = queue.Queue()
        self.episode_dir = ROOT / 'data' / 'transcripts'
        master = ROOT / 'data' / 'episodes.json'
        self.episodes = (json.loads(master.read_text(encoding='utf-8')).get('eps', [])
                         if master.exists() else [])
        self.metadata = {ep_key(e): e for e in self.episodes}
        paths = sorted(self.episode_dir.glob('*.json'),
                       key=lambda p: (self.metadata.get(p.stem, {}).get('d', ''), p.stem),
                       reverse=True)
        self.labels = {f'{p.stem} — {self.metadata.get(p.stem, {}).get("t", "Transcript")}': p
                       for p in paths}
        self._build_ui()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self._poll)
        initial = next((label for label, path in self.labels.items()
                        if path.stem == str(episode)), next(iter(self.labels), ''))
        if initial:
            self.episode_choice.set(initial)
            self.open_episode()
        else:
            self.status.set('No transcripts found in data/transcripts/.')

    def _build_ui(self):
        toolbar = ttk.Frame(self, padding=10)
        toolbar.pack(fill='x')
        ttk.Label(toolbar, text='Episode').pack(side='left', padx=(0, 8))
        self.episode_choice = tk.StringVar()
        self.episode_box = ttk.Combobox(toolbar, textvariable=self.episode_choice,
                                        values=list(self.labels), state='readonly', width=75)
        self.episode_box.pack(side='left', fill='x', expand=True)
        self.episode_box.bind('<<ComboboxSelected>>', lambda event: self.open_episode())
        self.fix_button = ttk.Button(toolbar, text='FIX', command=self.fix)
        self.fix_button.pack(side='left', padx=10)
        self.save_button = ttk.Button(toolbar, text='SAVE', command=self.save)
        self.save_button.pack(side='left')
        self.summary = tk.StringVar()
        ttk.Label(self, textvariable=self.summary, padding=(10, 3)).pack(anchor='w')
        ttk.Label(self, text='Listen, choose a speaker, then tick “Correct” for trusted examples. '
                  'FIX keeps checked lines fixed; SAVE writes the displayed assignments.',
                  padding=(10, 3), wraplength=1100).pack(anchor='w')
        actions = ttk.Frame(self, padding=(10, 8))
        actions.pack(fill='x')
        self.add_button = ttk.Button(actions, text='Add speaker…', command=self.add_speaker)
        self.add_button.pack(side='left')
        ttk.Button(actions, text='Stop audio', command=self.stop_audio).pack(side='left', padx=8)
        self.previous = ttk.Button(actions, text='Previous', command=lambda: self.turn_page(-1))
        self.previous.pack(side='left', padx=(25, 5))
        self.next = ttk.Button(actions, text='Next', command=lambda: self.turn_page(1))
        self.next.pack(side='left')
        self.page_label = tk.StringVar()
        ttk.Label(actions, textvariable=self.page_label).pack(side='left', padx=10)
        ttk.Label(actions, text='Go to line:').pack(side='left', padx=(20, 5))
        self.jump = ttk.Entry(actions, width=7)
        self.jump.pack(side='left')
        self.jump.bind('<Return>', lambda event: self.jump_to_line())
        ttk.Button(actions, text='Go', command=self.jump_to_line).pack(side='left', padx=5)
        container = ttk.Frame(self)
        container.pack(fill='both', expand=True, padx=10)
        self.canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.rows_frame = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window((0, 0), window=self.rows_frame, anchor='nw')
        self.rows_frame.bind('<Configure>', lambda event: self.canvas.configure(
            scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure(
            self.window, width=event.width))
        self.bind_all('<MouseWheel>', self._mousewheel)
        self.status = tk.StringVar(value='Ready.')
        ttk.Label(self, textvariable=self.status, padding=10, wraplength=1100).pack(fill='x')

    def _mousewheel(self, event):
        # Comboboxes should never silently change assignment on a scroll gesture.
        if isinstance(event.widget, ttk.Combobox):
            return 'break'
        self.canvas.yview_scroll(-int(event.delta / 120), 'units')

    def _summary(self):
        if not self.session:
            return
        session = self.session
        names = {s['id']: s['name'] for s in session.transcript['speakers']}
        trained = {session.transcript['segments'][i]['speaker'] for i in session.confirmed}
        missing = [name for sid, name in names.items() if sid not in trained]
        self.summary.set(f'{len(session.transcript["segments"])} lines · '
                         f'{len(session.confirmed)} confirmed · '
                         f'{"Unsaved changes" if session.dirty else "Saved"} · '
                         f'No checked examples: {", ".join(missing) or "none"}')

    def render_rows(self):
        for child in self.rows_frame.winfo_children():
            child.destroy()
        if not self.session:
            return
        segments = self.session.transcript['segments']
        speakers = self.session.transcript['speakers']
        names = {s['id']: s['name'] for s in speakers}
        ids = {s['name']: s['id'] for s in speakers}
        start = self.page * self.PAGE_SIZE
        for index in range(start, min(start + self.PAGE_SIZE, len(segments))):
            segment = segments[index]
            frame = ttk.Frame(self.rows_frame, padding=(5, 8))
            frame.pack(fill='x')
            ttk.Label(frame, text=f'#{index + 1}  {timestamp(segment.get("start"))} – '
                      f'{timestamp(segment.get("end"))}').grid(row=0, column=0, sticky='w')
            play = ttk.Button(frame, text='Listen', command=lambda i=index: self.play(i))
            play.grid(row=0, column=1, padx=8)
            choice = ttk.Combobox(frame, values=list(ids), state='readonly', width=27)
            choice.set(names[segment['speaker']])
            choice.grid(row=0, column=2, padx=8)
            choice.bind('<MouseWheel>', lambda event: 'break')
            choice.bind('<<ComboboxSelected>>',
                        lambda event, i=index, box=choice: self.assign(i, ids[box.get()]))
            checked = tk.BooleanVar(value=index in self.session.confirmed)
            check = ttk.Checkbutton(frame, text='Correct', variable=checked,
                                    command=lambda i=index, v=checked: self.confirm(i, v.get()))
            check.grid(row=0, column=3, padx=8)
            review = self.session.reviews.get(index)
            if review:
                scores = ', '.join(f'{names[sid]} {score:.3f}'
                                   for sid, score in review.get('scores', {}).items())
                ttk.Label(frame, text=f'{review["status"]}  {scores}', wraplength=1000).grid(
                    row=2, column=0, columnspan=4, sticky='w', pady=(3, 0))
            ttk.Label(frame, text=segment.get('text', ''), wraplength=max(650, self.winfo_width() - 90),
                      justify='left').grid(row=1, column=0, columnspan=4, sticky='w', pady=(6, 0))
            ttk.Separator(self.rows_frame).pack(fill='x')
            if self.busy:
                for widget in (play, choice, check):
                    widget.configure(state='disabled')
        self.page_label.set(f'Lines {start + 1 if segments else 0}–'
                            f'{min(start + self.PAGE_SIZE, len(segments))} / {len(segments)}')
        self.previous.configure(state='normal' if self.page > 0 else 'disabled')
        self.next.configure(state='normal' if start + self.PAGE_SIZE < len(segments) else 'disabled')
        self._summary()

    def assign(self, index, speaker):
        self.session.assign(index, speaker)
        self._summary()

    def confirm(self, index, value):
        if value:
            self.session.confirmed.add(index)
        else:
            self.session.confirmed.discard(index)
        self._summary()

    def discard_ok(self):
        if not self.session or not self.session.dirty:
            return True
        answer = messagebox.askyesnocancel('Unsaved changes', 'Save changes before continuing?', parent=self)
        if answer is None:
            return False
        return self.save() if answer else True

    def open_episode(self):
        if self.busy:
            return
        previous_path = self.session.path if self.session else None
        if not self.discard_ok():
            self.episode_choice.set(next(label for label, path in self.labels.items() if path == previous_path))
            return
        try:
            replacement = EditorSession(self.labels[self.episode_choice.get()])
        except Exception as exc:
            messagebox.showerror('Cannot open episode', str(exc), parent=self)
            if previous_path:
                self.episode_choice.set(next(label for label, path in self.labels.items() if path == previous_path))
            return
        self.stop_audio()
        if self.session:
            self.session.close()
        self.session = replacement
        self.audio = None
        self.page = 0
        self.render_rows()
        self.status.set('Ready. Correct checkboxes start unchecked for this episode.')

    def turn_page(self, delta):
        if self.session:
            self.page += delta
            self.render_rows()
            self.canvas.yview_moveto(0)

    def jump_to_line(self):
        if not self.session:
            return
        try:
            index = int(self.jump.get()) - 1
            if not 0 <= index < len(self.session.transcript['segments']):
                raise ValueError()
        except ValueError:
            messagebox.showerror('Line number', 'Enter an existing line number.', parent=self)
            return
        self.page = index // self.PAGE_SIZE
        self.render_rows()
        self.canvas.yview_moveto(0)

    def add_speaker(self):
        if not self.session:
            return
        name = simpledialog.askstring('Add speaker', 'Speaker name:', parent=self)
        if name:
            self.session.add_speaker(name)
            self.render_rows()

    def _ensure_audio(self):
        if self.audio is None:
            key = self.session.path.stem
            path = ROOT / 'data' / 'mp3' / f'{key}.mp3'
            if not path.exists():
                source = self.session.transcript.get('source', {}).get('audio')
                url = source or self.metadata.get(key, {}).get('mp3')
                if not url:
                    raise ValueError(f'No audio URL. Put the episode MP3 at {path}.')
                self.messages.put(('status', 'Downloading episode audio…'))
                # A failed download never leaves a partial cache entry.
                partial = path.with_suffix('.download')
                try:
                    download_mp3(url, partial)
                    partial.replace(path)
                finally:
                    partial.unlink(missing_ok=True)
            self.messages.put(('status', 'Loading episode audio…'))
            self.audio = load_audio(path)
        return self.audio

    def _run(self, work, done):
        if self.busy or not self.session:
            return
        self.busy = True
        self.stop_audio()
        for widget in (self.fix_button, self.save_button, self.add_button, self.episode_box):
            widget.configure(state='disabled')
        self.render_rows()

        def worker():
            try:
                result = work()
                self.messages.put(('done', (done, result)))
            except (Exception, SystemExit) as exc:
                self.messages.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == 'status':
                    self.status.set(payload)
                    continue
                self.busy = False
                for widget in (self.fix_button, self.save_button, self.add_button):
                    widget.configure(state='normal')
                self.episode_box.configure(state='readonly')
                self.render_rows()
                if kind == 'error':
                    self.status.set('Operation failed. Assignments have not been saved.')
                    messagebox.showerror('Diarization editor', payload, parent=self)
                else:
                    callback, result = payload
                    callback(result)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def play(self, index):
        def work():
            import numpy as np
            clip = audio_clip(self._ensure_audio(), self.session.transcript['segments'][index])
            if sys.platform == 'win32':
                import winsound
                path = Path(self.session.temp.name) / 'preview.wav'
                with wave.open(str(path), 'wb') as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(SAMPLING_RATE)
                    wav.writeframes((np.clip(clip, -1, 1) * 32767).astype('<i2').tobytes())
                winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                try:
                    import sounddevice
                except ImportError as exc:
                    raise RuntimeError('Audio playback on macOS/Linux needs: pip install sounddevice') from exc
                sounddevice.play(clip, SAMPLING_RATE)
        self._run(work, lambda result: self.status.set(f'Playing line {index + 1}.'))

    def stop_audio(self):
        if sys.platform == 'win32':
            import winsound
            winsound.PlaySound(None, 0)
        elif 'sounddevice' in sys.modules:
            sys.modules['sounddevice'].stop()

    def fix(self):
        if not self.session or self.busy:
            return
        groups = {self.session.transcript['segments'][i]['speaker'] for i in self.session.confirmed}
        if len(groups) < 2:
            messagebox.showerror('Trusted examples needed',
                                 'Mark correct examples for at least two different speakers.', parent=self)
            return

        def work():
            audio = self._ensure_audio()
            if self.encoder is None:
                self.messages.put(('status', 'Loading Resemblyzer (first run may download model weights)…'))
                from resemblyzer import VoiceEncoder, preprocess_wav
                self.encoder, self.preprocess = VoiceEncoder(), preprocess_wav
            return self.session.fix(audio, self.encoder, self.preprocess,
                                    lambda message: self.messages.put(('status', message)))

        def done(result):
            rows, folder = result
            changed = sum(row['status'] == 'changed' for row in rows)
            skipped = sum(row['status'] not in ('changed', 'confirmed') for row in rows)
            self.status.set(f'FIX: {changed} changes, {skipped} unchanged/unusable or tied lines. '
                            f'Review, fine-tune and FIX again, or SAVE. Temporary profiles: {folder}')
        self._run(work, done)

    def save(self):
        if not self.session or self.busy:
            return False
        try:
            backup = self.session.save()
        except Exception as exc:
            messagebox.showerror('Cannot save', str(exc), parent=self)
            return False
        self._summary()
        self.status.set(f'Saved {self.session.path.name}. Backup: {backup.name}')
        return True

    def close(self):
        if self.busy:
            messagebox.showinfo('Operation in progress', 'Wait for the current audio/FIX operation to finish.', parent=self)
            return
        if self.discard_ok():
            self.stop_audio()
            if self.session:
                self.session.close()
            self.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--episode', help='Open this episode immediately (e.g. 327 or x5005)')
    args = parser.parse_args()
    DiarizationEditor(args.episode).mainloop()


if __name__ == '__main__':
    main()
