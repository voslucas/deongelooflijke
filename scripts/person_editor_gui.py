"""
GUI tool for adding missing social links and profile images to podcast guests.

Usage:
    python scripts/person_editor_gui.py

Left panel: guests missing a LinkedIn URL or a profile image.
Right panel: paste a LinkedIn URL and/or paste an image from the clipboard, then Save.
"""

import io
import json
import re
import sys
import threading
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
PERSONS_DIR = REPO_ROOT / "data" / "persons"
IMAGES_DIR = PERSONS_DIR / "images"
EPISODES_FILE = REPO_ROOT / "data" / "episodes.json"

IMAGES_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Slug utility (mirrors utils.py)
# ---------------------------------------------------------------------------
def slug(name: str) -> str:
    s = unicodedata.normalize("NFD", name.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------
def load_episodes() -> dict:
    with open(EPISODES_FILE, encoding="utf-8") as f:
        return json.load(f)


def person_json_path(name: str) -> Path:
    return PERSONS_DIR / f"{slug(name)}.json"


def person_image_path(name: str) -> Path | None:
    """Return the existing image path for this person, or None."""
    s = slug(name)
    for ext in ("jpg", "jpeg", "png", "webp", "jfif"):
        p = IMAGES_DIR / f"{s}.{ext}"
        if p.exists():
            return p
    return None


def load_person_data(name: str) -> dict:
    p = person_json_path(name)
    if p.exists():
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}


def x_social(socials: dict) -> str:
    """Return the X/Twitter URL from a socials dict, accepting both key spellings."""
    return socials.get("twitter") or socials.get("x") or ""


def is_missing(name: str) -> bool:
    data = load_person_data(name)
    socials = data.get("socials", {})
    has_social = bool(socials.get("linkedin") or x_social(socials))
    has_image = person_image_path(name) is not None
    return not has_social or not has_image


def build_appearance_index(eps: list[dict]) -> dict[str, tuple[int, str]]:
    """Return {name: (count, latest_date)} from the episodes list."""
    index: dict[str, tuple[int, str]] = {}
    for ep in eps:
        date = ep.get("d", "")
        for name in ep.get("g", []):
            count, latest = index.get(name, (0, ""))
            index[name] = (count + 1, max(latest, date))
    return index


def get_missing_persons(bios: dict, eps: list[dict]) -> list[str]:
    appearance = build_appearance_index(eps)
    missing = [name for name in bios if is_missing(name)]
    # Sort: most appearances first, then most recent first
    return sorted(
        missing,
        key=lambda n: (-(appearance.get(n, (0, ""))[0]), appearance.get(n, (0, ""))[1]),
        reverse=False,
    )


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------
class PersonEditorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Personen editor — sociale links & afbeeldingen")
        self.geometry("900x620")
        self.resizable(True, True)
        self.configure(bg="#fdf6e3")

        self._episodes = load_episodes()
        self._bios = self._episodes.get("bios", {})
        self._eps = self._episodes.get("eps", [])
        self._missing = []
        self._selected_name: str | None = None
        self._pasted_image: Image.Image | None = None
        self._photo_ref = None  # keep reference so GC won't collect it

        self._build_ui()
        self._refresh_list()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#fdf6e3")
        style.configure("TLabel", background="#fdf6e3", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10))
        style.configure("Header.TLabel", font=("Georgia", 12, "bold"))
        style.configure("Sub.TLabel", font=("Segoe UI", 9), foreground="#8a7355")

        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        # --- Left: person list ---
        left = ttk.Frame(pane)
        pane.add(left, weight=1)

        ttk.Label(left, text="Personen zonder link/afbeelding", style="Header.TLabel").pack(
            anchor="w", pady=(0, 6)
        )

        self._count_var = tk.StringVar()
        ttk.Label(left, textvariable=self._count_var, style="Sub.TLabel").pack(anchor="w")

        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        self._listbox = tk.Listbox(
            list_frame,
            yscrollcommand=sb.set,
            font=("Segoe UI", 10),
            selectbackground="#7c3aed",
            selectforeground="white",
            activestyle="none",
            bg="#fdf6e3",
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=1,
            highlightcolor="#c8b97a",
        )
        sb.config(command=self._listbox.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._listbox.bind("<<ListboxSelect>>", self._on_select)

        # --- Right: editor ---
        right = ttk.Frame(pane)
        pane.add(right, weight=2)

        self._name_var = tk.StringVar(value="— selecteer een persoon —")
        ttk.Label(right, textvariable=self._name_var, style="Header.TLabel").pack(
            anchor="w", pady=(0, 10)
        )

        # Status row
        status_frame = ttk.Frame(right)
        status_frame.pack(fill=tk.X, pady=(0, 8))
        self._status_linkedin = tk.StringVar()
        self._status_x = tk.StringVar()
        self._status_image = tk.StringVar()
        ttk.Label(status_frame, textvariable=self._status_linkedin, style="Sub.TLabel").pack(anchor="w")
        ttk.Label(status_frame, textvariable=self._status_x, style="Sub.TLabel").pack(anchor="w")
        ttk.Label(status_frame, textvariable=self._status_image, style="Sub.TLabel").pack(anchor="w")

        # LinkedIn
        ttk.Label(right, text="LinkedIn URL").pack(anchor="w")
        self._linkedin_var = tk.StringVar()
        ttk.Entry(right, textvariable=self._linkedin_var, font=("Segoe UI", 10)).pack(
            fill=tk.X, pady=(2, 8)
        )

        # X (Twitter)
        x_row = ttk.Frame(right)
        x_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(x_row, text="X / Twitter URL").pack(side=tk.LEFT)
        self._x_fetch_btn = tk.Button(
            x_row,
            text="Haal profielfoto op",
            command=self._fetch_x_image,
            bg="#1a1a1a",
            fg="white",
            font=("Segoe UI", 9),
            relief=tk.FLAT,
            padx=8,
            pady=2,
            cursor="hand2",
        )
        self._x_fetch_btn.pack(side=tk.RIGHT)
        self._x_var = tk.StringVar()
        ttk.Entry(right, textvariable=self._x_var, font=("Segoe UI", 10)).pack(
            fill=tk.X, pady=(2, 0)
        )

        # Slug preview
        slug_frame = ttk.Frame(right)
        slug_frame.pack(fill=tk.X, pady=(8, 12))
        ttk.Label(slug_frame, text="Slug:", style="Sub.TLabel").pack(side=tk.LEFT)
        self._slug_var = tk.StringVar()
        ttk.Label(slug_frame, textvariable=self._slug_var, style="Sub.TLabel", foreground="#7c3aed").pack(
            side=tk.LEFT, padx=(4, 0)
        )

        # Image paste area
        ttk.Label(right, text="Profielfoto (Ctrl+V of klik om te plakken)").pack(anchor="w")
        self._image_frame = tk.Frame(
            right,
            width=200,
            height=200,
            bg="#f0e9d6",
            relief=tk.SUNKEN,
            borderwidth=1,
            cursor="hand2",
        )
        self._image_frame.pack(anchor="w", pady=(2, 2))
        self._image_frame.pack_propagate(False)
        self._image_label = tk.Label(
            self._image_frame,
            text="Klik hier en druk Ctrl+V\nom een afbeelding te plakken",
            bg="#f0e9d6",
            fg="#8a7355",
            font=("Segoe UI", 9),
            justify=tk.CENTER,
        )
        self._image_label.pack(expand=True)
        self._image_frame.bind("<Button-1>", self._focus_image_area)
        self._image_label.bind("<Button-1>", self._focus_image_area)
        self.bind("<Control-v>", self._paste_image)

        self._img_status_var = tk.StringVar()
        ttk.Label(right, textvariable=self._img_status_var, style="Sub.TLabel").pack(anchor="w", pady=(0, 12))

        # Save button
        save_btn = tk.Button(
            right,
            text="  Opslaan  ",
            command=self._save,
            bg="#7c3aed",
            fg="white",
            font=("Segoe UI", 11, "bold"),
            relief=tk.FLAT,
            padx=16,
            pady=8,
            cursor="hand2",
        )
        save_btn.pack(anchor="w")

        # Clear image button
        clear_btn = tk.Button(
            right,
            text="Afbeelding wissen",
            command=self._clear_image,
            bg="#fdf6e3",
            fg="#8a7355",
            font=("Segoe UI", 9),
            relief=tk.FLAT,
            cursor="hand2",
        )
        clear_btn.pack(anchor="w", pady=(4, 0))

    # ------------------------------------------------------------------
    # List management
    # ------------------------------------------------------------------
    def _refresh_list(self):
        self._missing = get_missing_persons(self._bios, self._eps)
        appearance = build_appearance_index(self._eps)
        self._listbox.delete(0, tk.END)
        for name in self._missing:
            count, latest = appearance.get(name, (0, ""))
            label = f"{name}  ({count}×  {latest})"
            self._listbox.insert(tk.END, label)
        self._count_var.set(f"{len(self._missing)} personen ontbreken data")

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    def _on_select(self, _event=None):
        sel = self._listbox.curselection()
        if not sel:
            return
        name = self._missing[sel[0]]
        self._load_person(name)

    def _load_person(self, name: str):
        self._selected_name = name
        self._pasted_image = None
        self._photo_ref = None
        self._name_var.set(name)
        self._slug_var.set(slug(name))

        data = load_person_data(name)
        socials = data.get("socials", {})
        self._linkedin_var.set(socials.get("linkedin", ""))
        self._x_var.set(x_social(socials))

        # Status
        img_path = person_image_path(name)
        self._status_linkedin.set("✓ LinkedIn aanwezig" if socials.get("linkedin") else "✗ LinkedIn ontbreekt")
        self._status_x.set("✓ X aanwezig" if x_social(socials) else "✗ X ontbreekt")
        self._status_image.set(
            f"✓ Afbeelding: {img_path.name}" if img_path else "✗ Afbeelding ontbreekt"
        )

        # Show existing image if present
        self._image_label.config(text="")
        if img_path:
            self._show_image_file(img_path)
            self._img_status_var.set(f"Huidig: {img_path.name}")
        else:
            self._image_label.config(
                image="",
                text="Klik hier en druk Ctrl+V\nom een afbeelding te plakken",
            )
            self._img_status_var.set("")

    # ------------------------------------------------------------------
    # Image handling
    # ------------------------------------------------------------------
    def _focus_image_area(self, _event=None):
        self._image_frame.focus_set()
        self._image_label.focus_set()
        self.focus_set()

    def _paste_image(self, _event=None):
        if self._selected_name is None:
            messagebox.showwarning("Geen selectie", "Selecteer eerst een persoon.")
            return
        try:
            from PIL import ImageGrab
            img = ImageGrab.grabclipboard()
            if img is None:
                messagebox.showinfo(
                    "Geen afbeelding",
                    "Het klembord bevat geen afbeelding.\n"
                    "Kopieer een afbeelding en probeer opnieuw.",
                )
                return
            if isinstance(img, list):
                # File list pasted — load first file
                img = Image.open(img[0])
            self._pasted_image = img.convert("RGB")
            self._show_pil_image(self._pasted_image)
            self._img_status_var.set(
                f"Geplakt: {self._pasted_image.size[0]}×{self._pasted_image.size[1]} px"
            )
        except Exception as exc:
            messagebox.showerror("Fout bij plakken", str(exc))

    def _show_pil_image(self, img: Image.Image):
        thumb = img.copy()
        thumb.thumbnail((196, 196))
        self._photo_ref = ImageTk.PhotoImage(thumb)
        self._image_label.config(image=self._photo_ref, text="")

    def _show_image_file(self, path: Path):
        try:
            img = Image.open(path)
            self._show_pil_image(img)
        except Exception:
            self._image_label.config(text=f"(kan niet laden: {path.name})", image="")

    def _clear_image(self):
        self._pasted_image = None
        self._photo_ref = None
        self._image_label.config(image="", text="Klik hier en druk Ctrl+V\nom een afbeelding te plakken")
        self._img_status_var.set("")

    # ------------------------------------------------------------------
    # X / Twitter image fetch
    # ------------------------------------------------------------------
    def _x_username_from_url(self, url: str) -> str | None:
        """Extract username from https://x.com/username or https://twitter.com/username."""
        url = url.strip().rstrip("/")
        m = re.search(r"(?:x\.com|twitter\.com)/([A-Za-z0-9_]{1,50})(?:[/?#]|$)", url)
        return m.group(1) if m else None

    def _fetch_x_image(self):
        if self._selected_name is None:
            messagebox.showwarning("Geen selectie", "Selecteer eerst een persoon.")
            return
        x_url = self._x_var.get().strip()
        if not x_url:
            messagebox.showwarning("Geen URL", "Vul een X/Twitter-URL in.")
            return
        username = self._x_username_from_url(x_url)
        if not username:
            messagebox.showwarning("Ongeldige URL", f"Kan geen gebruikersnaam vinden in:\n{x_url}")
            return

        self._x_fetch_btn.config(text="Bezig…", state=tk.DISABLED)
        self._img_status_var.set(f"Ophalen @{username}…")

        def _fetch():
            try:
                fetch_url = f"https://unavatar.io/twitter/{username}"
                req = urllib.request.Request(
                    fetch_url, headers={"User-Agent": "deongelooflijke-person-editor/1.0"}
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    data = resp.read()
                img = Image.open(io.BytesIO(data)).convert("RGB")
                self.after(0, lambda: self._on_x_image_fetched(img, username))
            except Exception as exc:
                self.after(0, lambda: self._on_x_image_error(str(exc)))

        threading.Thread(target=_fetch, daemon=True).start()

    def _on_x_image_fetched(self, img: Image.Image, username: str):
        self._pasted_image = img
        self._show_pil_image(img)
        self._img_status_var.set(
            f"@{username}: {img.size[0]}×{img.size[1]} px (via unavatar.io)"
        )
        self._x_fetch_btn.config(text="Haal profielfoto op", state=tk.NORMAL)

    def _on_x_image_error(self, msg: str):
        self._img_status_var.set(f"Ophalen mislukt: {msg}")
        self._x_fetch_btn.config(text="Haal profielfoto op", state=tk.NORMAL)
        messagebox.showerror("Fout", f"Kon profielfoto niet ophalen:\n{msg}")

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    def _save(self):
        if self._selected_name is None:
            messagebox.showwarning("Geen selectie", "Selecteer eerst een persoon.")
            return

        name = self._selected_name
        linkedin_url = self._linkedin_var.get().strip()
        x_url = self._x_var.get().strip()
        s = slug(name)

        # Validate URLs
        if linkedin_url and "linkedin.com" not in linkedin_url:
            messagebox.showwarning(
                "Ongeldige URL",
                "De URL lijkt geen LinkedIn-link te zijn.\nControleer het adres en probeer opnieuw.",
            )
            return
        if x_url and not re.search(r"(x\.com|twitter\.com)/", x_url):
            messagebox.showwarning(
                "Ongeldige URL",
                "De URL lijkt geen X/Twitter-link te zijn.\nControleer het adres en probeer opnieuw.",
            )
            return

        # Load existing data
        data = load_person_data(name)

        # Update socials
        changed = False
        for key, val in [("linkedin", linkedin_url), ("twitter", x_url)]:
            if val:
                if "socials" not in data:
                    data["socials"] = {}
                if data["socials"].get(key) != val:
                    data["socials"][key] = val
                    changed = True
        # Normalise legacy "x" key → "twitter"
        if x_url and "socials" in data and data["socials"].get("x"):
            del data["socials"]["x"]
            changed = True

        # Save image
        image_saved = False
        if self._pasted_image is not None:
            img_path = IMAGES_DIR / f"{s}.jpg"
            self._pasted_image.save(img_path, "JPEG", quality=90)
            image_saved = True
            self._img_status_var.set(f"Opgeslagen: {img_path.name}")

        # Save JSON only if something changed
        if changed or image_saved:
            json_path = person_json_path(name)
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            parts = []
            if changed:
                parts.append("JSON opgeslagen")
            if image_saved:
                parts.append(f"afbeelding → {s}.jpg")
            messagebox.showinfo("Opgeslagen", f"{name}\n" + " · ".join(parts))

            # Refresh list (person may now be complete)
            self._refresh_list()
            self._update_status_labels(name)
        else:
            messagebox.showinfo("Niets gewijzigd", "Er is niets om op te slaan.")

    def _update_status_labels(self, name: str):
        data = load_person_data(name)
        socials = data.get("socials", {})
        img_path = person_image_path(name)
        self._status_linkedin.set("✓ LinkedIn aanwezig" if socials.get("linkedin") else "✗ LinkedIn ontbreekt")
        self._status_x.set("✓ X aanwezig" if x_social(socials) else "✗ X ontbreekt")
        self._status_image.set(
            f"✓ Afbeelding: {img_path.name}" if img_path else "✗ Afbeelding ontbreekt"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    try:
        from PIL import Image, ImageTk, ImageGrab  # noqa: F401
    except ImportError:
        print("Pillow is vereist. Installeer het met:\n  pip install Pillow", file=sys.stderr)
        sys.exit(1)

    app = PersonEditorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
