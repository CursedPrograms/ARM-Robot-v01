# keys_window.jl - every key and joystick input in its own window (F1), the
# Julia counterpart of scripts/keymap.py's window. It shows scripts/keymap.json,
# which keymap.py writes (python scripts/keymap.py --json scripts/keymap.json).

const KEYMAP_PATH = normpath(joinpath(@__DIR__, "..", "keymap.json"))
const KEYS_WIDTH, KEYS_HEIGHT = 580, 760
const KEYS_PAD = 16
const KEYS_KEY_COLUMN = 180

mutable struct KeysWindow
    window::Ptr{SDL_Window}
    renderer::Ptr{SDL_Renderer}
    id::UInt32
    title::String
    sections::Vector{Tuple{String,Vector{Tuple{String,String}}}}  # (heading, [(key, does)]); an empty key is a note
    fonts::Dict{Symbol,Ptr{TTF_Font}}
    scroll::Int
    height::Int
end

# Read again each time the window opens, so a fresh keymap.json shows without a restart.
function load_keymap()
    try
        data = JSON3.read(read(KEYMAP_PATH, String), Dict{String,Any})
        sections = [(String(s["title"]), [(String(r[1]), String(r[2])) for r in s["keys"]]) for s in data["sections"]]
        return String(get(data, "title", "ARM - controls")), sections
    catch e
        return "ARM - controls", [("keymap.json not readable",
                                   [("", sprint(showerror, e)), ("", "run: python scripts/keymap.py --json scripts/keymap.json")])]
    end
end

# Courier New like keymap.py's window, else the controller's own font.
function keys_font(name, fallback, size)
    path = joinpath(get(ENV, "WINDIR", "C:\\Windows"), "Fonts", name)
    return TTF_OpenFont(Sys.iswindows() && isfile(path) ? path : fallback, size)
end

function open_keys_window(font_path)
    title, sections = load_keymap()
    window = SDL_CreateWindow(title, SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, KEYS_WIDTH, KEYS_HEIGHT,
                              SDL_WINDOW_SHOWN | SDL_WINDOW_RESIZABLE)
    window == C_NULL && return nothing
    renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED)
    fonts = Dict(
        :title => keys_font("courbd.ttf", font_path, 20),
        :heading => keys_font("courbd.ttf", font_path, 16),
        :key => keys_font("courbd.ttf", font_path, 14),
        :text => keys_font("cour.ttf", font_path, 14),
        :note => keys_font("couri.ttf", font_path, 13),
    )
    return KeysWindow(window, renderer, SDL_GetWindowID(window), title, sections, fonts, 0, 0)
end

function close_keys_window!(kw::KeysWindow)
    for f in values(kw.fonts)
        f != C_NULL && TTF_CloseFont(f)
    end
    SDL_DestroyRenderer(kw.renderer)
    SDL_DestroyWindow(kw.window)
end

function scroll_keys_window!(kw::KeysWindow, dy)
    h = Ref{Cint}(0)
    SDL_GetWindowSize(kw.window, Ref{Cint}(0), h)
    kw.scroll = clamp(kw.scroll + dy, 0, max(0, kw.height - Int(h[])))
end

# Text wrapped to `width` at (x, y), drawn only when `paint` is set; returns its height.
function wrapped_text!(renderer, font, text, x, y, width, color, paint)
    isempty(text) && return 0
    surf = TTF_RenderText_Blended_Wrapped(font, text, SDL_Color(color[1], color[2], color[3], 255), width)
    surf == C_NULL && return 0
    s = unsafe_load(surf)
    if paint
        tex = SDL_CreateTextureFromSurface(renderer, surf)
        SDL_RenderCopy(renderer, tex, C_NULL, Ref(SDL_Rect(x, y, s.w, s.h)))
        SDL_DestroyTexture(tex)
    end
    SDL_FreeSurface(surf)
    return Int(s.h)
end

# A table row: the key in bold on the left, what it does on the right; a row
# without a key is a dim note across the table. Returns its height.
function keys_row!(kw::KeysWindow, key, does, y, width, paint)
    r = kw.renderer
    isempty(key) && return wrapped_text!(r, kw.fonts[:note], does, KEYS_PAD + 8, y, width - 2KEYS_PAD - 16, SCHEME["text_dim"], paint)
    hk = wrapped_text!(r, kw.fonts[:key], key, KEYS_PAD + 8, y, KEYS_KEY_COLUMN - KEYS_PAD - 12, TEXT_COLOR, paint)
    hd = wrapped_text!(r, kw.fonts[:text], does, KEYS_KEY_COLUMN, y, width - KEYS_KEY_COLUMN - KEYS_PAD - 8, TEXT_COLOR, paint)
    return max(hk, hd)
end

# The tables, in the same colours as the controller.
function draw_keys_window!(kw::KeysWindow)
    r = kw.renderer
    w = Ref{Cint}(0)
    SDL_GetWindowSize(kw.window, w, Ref{Cint}(0))
    width = Int(w[])
    SDL_SetRenderDrawColor(r, BG_COLOR..., 255)
    SDL_RenderClear(r)

    accent = SCHEME["accent"]
    y = KEYS_PAD - kw.scroll
    y += wrapped_text!(r, kw.fonts[:title], uppercase(kw.title), KEYS_PAD, y, width - 2KEYS_PAD, accent, true) + 8
    for (heading, rows) in kw.sections
        y += 12
        y += wrapped_text!(r, kw.fonts[:heading], heading, KEYS_PAD, y, width - 2KEYS_PAD, accent, true) + 4
        for (key, does) in rows
            h = keys_row!(kw, key, does, y, width, false)
            fill_rect!(r, (KEYS_PAD, y - 2, width - 2KEYS_PAD, h + 4), SCHEME["panel"])
            keys_row!(kw, key, does, y, width, true)
            y += h + 4
        end
    end
    kw.height = y + kw.scroll + KEYS_PAD
    SDL_RenderPresent(r)
end
