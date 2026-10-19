#include "keys_window.h"

#include "colour_scheme.h"
#include "json.hpp"
#include "motor_config.h"

#include <algorithm>
#include <fstream>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace {

struct Section {
    std::string title;
    std::vector<std::pair<std::string, std::string>> keys; // (key, does); an empty key is a note
};

struct Keymap {
    std::string title = "ARM - controls";
    std::vector<Section> sections;
};

constexpr int PAD = 16;
constexpr int KEY_COLUMN = 180;

HWND g_window = nullptr;
Keymap g_keymap;
int g_scroll = 0;
int g_contentHeight = 0;
HFONT g_titleFont, g_headingFont, g_keyFont, g_textFont, g_noteFont;

Keymap loadKeymap() {
    Keymap km;
    std::string path = repoRoot() + "\\scripts\\keymap.json";
    std::ifstream f(path, std::ios::binary);
    if (!f) {
        km.sections.push_back({"keymap.json not found", {{"", "run: python scripts/keymap.py --json scripts/keymap.json"}}});
        return km;
    }
    std::ostringstream ss;
    ss << f.rdbuf();
    Json root = Json::parse(ss.str());
    km.title = root.get("title", km.title);
    if (const Json* sections = root.find("sections")) {
        for (const Json& s : sections->arr_value) {
            Section section;
            section.title = s.get("title", std::string());
            if (const Json* keys = s.find("keys")) {
                for (const Json& row : keys->arr_value) {
                    if (row.arr_value.size() == 2) section.keys.push_back({row.arr_value[0].asString(), row.arr_value[1].asString()});
                }
            }
            km.sections.push_back(std::move(section));
        }
    }
    return km;
}

HFONT makeFont(int height, bool bold, bool italic = false) {
    return CreateFontA(height, 0, 0, 0, bold ? FW_BOLD : FW_NORMAL, italic, FALSE, FALSE, DEFAULT_CHARSET,
                       OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, FIXED_PITCH, "Courier New");
}

// Lays out (and, with draw, paints) the tables from y = -scroll; returns the full height.
int layout(HDC dc, int width, bool draw) {
    int y = PAD - g_scroll;
    // Measures s wrapped to w at (x, y); paints it too when paint is set.
    auto text = [&](HFONT font, COLORREF colour, int x, int w, const std::string& s, bool paint) {
        SelectObject(dc, font);
        RECT r = {x, y, x + w, y};
        DrawTextA(dc, s.c_str(), -1, &r, DT_LEFT | DT_WORDBREAK | DT_NOPREFIX | DT_CALCRECT);
        if (paint) {
            SetTextColor(dc, colour);
            DrawTextA(dc, s.c_str(), -1, &r, DT_LEFT | DT_WORDBREAK | DT_NOPREFIX);
        }
        return static_cast<int>(r.bottom - r.top);
    };
    // A table row: the key in bold on the left, what it does on the right; a
    // row without a key is a dim note across the table.
    auto row = [&](const std::pair<std::string, std::string>& r, bool paint) {
        if (r.first.empty()) return text(g_noteFont, schemeColour("text_dim"), PAD + 8, width - 2 * PAD - 16, r.second, paint);
        int hk = text(g_keyFont, schemeColour("text"), PAD + 8, KEY_COLUMN - PAD - 12, r.first, paint);
        int hd = text(g_textFont, schemeColour("text"), KEY_COLUMN, width - KEY_COLUMN - PAD - 8, r.second, paint);
        return std::max(hk, hd);
    };

    std::string title = g_keymap.title;
    std::transform(title.begin(), title.end(), title.begin(), ::toupper);
    y += text(g_titleFont, schemeColour("accent"), PAD, width - 2 * PAD, title, draw) + 8;
    for (const auto& section : g_keymap.sections) {
        y += 12;
        y += text(g_headingFont, schemeColour("accent"), PAD, width - 2 * PAD, section.title, draw) + 4;
        for (const auto& r : section.keys) {
            int h = row(r, false);
            if (draw) {
                RECT band = {PAD, y - 2, width - PAD, y + h + 2};
                HBRUSH panel = CreateSolidBrush(schemeColour("panel"));
                FillRect(dc, &band, panel);
                DeleteObject(panel);
                row(r, true);
            }
            y += h + 4;
        }
    }
    return y + g_scroll + PAD;
}

void updateScrollBar(HWND hwnd) {
    RECT rc;
    GetClientRect(hwnd, &rc);
    int maxScroll = std::max(0, g_contentHeight - static_cast<int>(rc.bottom));
    g_scroll = std::clamp(g_scroll, 0, maxScroll);
    SCROLLINFO si = {sizeof(si), SIF_RANGE | SIF_PAGE | SIF_POS, 0, g_contentHeight, static_cast<UINT>(rc.bottom), g_scroll, 0};
    SetScrollInfo(hwnd, SB_VERT, &si, TRUE);
}

void scrollTo(HWND hwnd, int pos) {
    g_scroll = pos;
    updateScrollBar(hwnd);
    InvalidateRect(hwnd, nullptr, TRUE);
}

LRESULT CALLBACK KeysProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
        case WM_ERASEBKGND: {
            RECT rc;
            GetClientRect(hwnd, &rc);
            HBRUSH bg = CreateSolidBrush(schemeColour("background"));
            FillRect(reinterpret_cast<HDC>(wParam), &rc, bg);
            DeleteObject(bg);
            return 1;
        }
        case WM_PAINT: {
            PAINTSTRUCT ps;
            HDC dc = BeginPaint(hwnd, &ps);
            SetBkMode(dc, TRANSPARENT);
            RECT rc;
            GetClientRect(hwnd, &rc);
            int height = layout(dc, rc.right, true);
            EndPaint(hwnd, &ps);
            if (height != g_contentHeight) {
                g_contentHeight = height;
                updateScrollBar(hwnd);
            }
            return 0;
        }
        case WM_SIZE:
            InvalidateRect(hwnd, nullptr, TRUE);
            updateScrollBar(hwnd);
            return 0;
        case WM_MOUSEWHEEL:
            scrollTo(hwnd, g_scroll - GET_WHEEL_DELTA_WPARAM(wParam) / WHEEL_DELTA * 40);
            return 0;
        case WM_VSCROLL: {
            SCROLLINFO si = {sizeof(si), SIF_ALL};
            GetScrollInfo(hwnd, SB_VERT, &si);
            int pos = si.nPos;
            switch (LOWORD(wParam)) {
                case SB_LINEUP: pos -= 20; break;
                case SB_LINEDOWN: pos += 20; break;
                case SB_PAGEUP: pos -= static_cast<int>(si.nPage); break;
                case SB_PAGEDOWN: pos += static_cast<int>(si.nPage); break;
                case SB_THUMBTRACK: pos = si.nTrackPos; break;
            }
            scrollTo(hwnd, pos);
            return 0;
        }
        case WM_KEYDOWN:
            if (wParam == VK_ESCAPE || wParam == VK_F1) DestroyWindow(hwnd);
            else if (wParam == VK_DOWN) scrollTo(hwnd, g_scroll + 20);
            else if (wParam == VK_UP) scrollTo(hwnd, g_scroll - 20);
            return 0;
        case WM_DESTROY:
            g_window = nullptr;
            return 0;
    }
    return DefWindowProcA(hwnd, msg, wParam, lParam);
}

} // namespace

void openKeysWindow(HWND owner) {
    if (g_window) {
        SetForegroundWindow(g_window);
        return;
    }
    static bool registered = false;
    if (!registered) {
        WNDCLASSA wc = {};
        wc.lpfnWndProc = KeysProc;
        wc.hInstance = GetModuleHandle(nullptr);
        wc.lpszClassName = "ArmKeysWindowCpp";
        wc.hIcon = LoadIconA(GetModuleHandle(nullptr), MAKEINTRESOURCEA(1));
        wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
        RegisterClassA(&wc);
        g_titleFont = makeFont(22, true);
        g_headingFont = makeFont(17, true);
        g_keyFont = makeFont(15, true);
        g_textFont = makeFont(14, false);
        g_noteFont = makeFont(14, false, true);
        registered = true;
    }
    g_keymap = loadKeymap(); // read it again each time, so a fresh keymap.json shows without a restart
    g_scroll = 0;
    g_contentHeight = 0;
    g_window = CreateWindowExA(0, "ArmKeysWindowCpp", g_keymap.title.c_str(), WS_OVERLAPPEDWINDOW | WS_VSCROLL,
                               CW_USEDEFAULT, CW_USEDEFAULT, 580, 760, owner, nullptr, GetModuleHandle(nullptr), nullptr);
    ShowWindow(g_window, SW_SHOW);
}
