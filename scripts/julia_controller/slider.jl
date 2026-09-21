# slider.jl - On-screen drag slider widget, drawn with SDL2. Julia
# counterpart of slider_controller.py's Slider class.

const SLIDER_X = 175
const SLIDER_WIDTH = 300
const KNOB_RADIUS = 9

mutable struct Slider
    label::String
    channel::Union{Int,Nothing}
    lo::Float64
    hi::Float64
    rest::Float64
    y::Int
    angle::Int
    dragging::Bool
end

function Slider(label, channel, lo, hi, rest, y)
    rest = clamp(rest, lo, hi)
    return Slider(label, channel, Float64(lo), Float64(hi), Float64(rest), Int(y), round(Int, rest), false)
end

value_to_x(s::Slider) = SLIDER_X + round(Int, (s.angle - s.lo) / (s.hi - s.lo) * SLIDER_WIDTH)

function x_to_value(s::Slider, x::Real)
    frac = clamp((x - SLIDER_X) / SLIDER_WIDTH, 0.0, 1.0)
    return round(Int, s.lo + frac * (s.hi - s.lo))
end

on_track(s::Slider, mx::Real, my::Real) =
    (SLIDER_X - KNOB_RADIUS) <= mx <= (SLIDER_X + SLIDER_WIDTH + KNOB_RADIUS) &&
    (s.y - KNOB_RADIUS) <= my <= (s.y + KNOB_RADIUS)

function slider_mouse_down!(s::Slider, mx, my)
    if on_track(s, mx, my)
        s.dragging = true
        s.angle = x_to_value(s, mx)
        return true
    end
    return false
end

slider_mouse_up!(s::Slider) = (s.dragging = false)

function slider_mouse_move!(s::Slider, mx)
    s.dragging && (s.angle = x_to_value(s, mx))
end
