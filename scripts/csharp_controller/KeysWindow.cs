// KeysWindow.cs - every key and joystick input in its own window (F1), the C#
// counterpart of scripts/keymap.py's window. It shows scripts/keymap.json,
// which keymap.py writes (python scripts/keymap.py --json scripts/keymap.json).

using System.Text.Json.Nodes;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;

namespace ArmController;

public sealed class KeysWindow : Window
{
    static KeysWindow? _open;

    /// <summary>Opens the window, or brings it to the front if it's already open.</summary>
    public static void Open(Window owner)
    {
        if (_open != null)
        {
            _open.Activate();
            return;
        }
        _open = new KeysWindow();
        _open.Closed += (_, _) => _open = null;
        _open.Show(owner);
    }

    KeysWindow()
    {
        var font = new FontFamily("Courier New");
        var (title, sections) = Load();
        Title = title;
        Width = 580;
        Height = 760;
        Background = ColourScheme.Brush("background");
        Foreground = ColourScheme.Brush("text");
        FontFamily = font;

        var body = new StackPanel { Margin = new Thickness(16, 14, 16, 16) };
        body.Children.Add(new TextBlock
        {
            Text = title.ToUpperInvariant(),
            FontSize = 18,
            FontWeight = FontWeight.Bold,
            Foreground = ColourScheme.Brush("accent"),
        });
        foreach (var (heading, rows) in sections)
        {
            body.Children.Add(new TextBlock
            {
                Text = heading,
                FontSize = 14,
                FontWeight = FontWeight.Bold,
                Foreground = ColourScheme.Brush("accent"),
                Margin = new Thickness(0, 12, 0, 4),
            });
            var table = new Grid { ColumnDefinitions = new ColumnDefinitions("160,*") };
            for (int i = 0; i < rows.Count; i++)
            {
                var (key, does) = rows[i];
                table.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
                if (key == "")
                {
                    // A row without a key is a note across the table.
                    var note = Cell(does, i, 0, 11, ColourScheme.Brush("text_dim"));
                    note.FontStyle = FontStyle.Italic;
                    Grid.SetColumnSpan(note, 2);
                    table.Children.Add(note);
                }
                else
                {
                    var k = Cell(key, i, 0, 12, ColourScheme.Brush("text"));
                    k.FontWeight = FontWeight.Bold;
                    table.Children.Add(k);
                    table.Children.Add(Cell(does, i, 1, 12, ColourScheme.Brush("text")));
                }
            }
            body.Children.Add(new Border { Background = ColourScheme.Brush("panel"), Child = table, Padding = new Thickness(0, 2) });
        }
        Content = new ScrollViewer { Content = body };
    }

    static TextBlock Cell(string text, int row, int column, double size, IBrush brush)
    {
        var cell = new TextBlock
        {
            Text = text,
            FontSize = size,
            Foreground = brush,
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(8, 2, 4, 2),
            VerticalAlignment = VerticalAlignment.Top,
        };
        Grid.SetRow(cell, row);
        Grid.SetColumn(cell, column);
        return cell;
    }

    // Read again each time the window opens, so a fresh keymap.json shows without a restart.
    static (string Title, List<(string Heading, List<(string Key, string Does)> Rows)> Sections) Load()
    {
        var sections = new List<(string, List<(string, string)>)>();
        string path = Path.Combine(Config.RepoRoot, "scripts", "keymap.json");
        try
        {
            var root = JsonNode.Parse(File.ReadAllText(path))!;
            foreach (var s in root["sections"]!.AsArray())
            {
                var rows = new List<(string, string)>();
                foreach (var r in s!["keys"]!.AsArray())
                    rows.Add(((string?)r![0] ?? "", (string?)r[1] ?? ""));
                sections.Add(((string?)s["title"] ?? "", rows));
            }
            return ((string?)root["title"] ?? "ARM - controls", sections);
        }
        catch (Exception e)
        {
            sections.Add(("keymap.json not readable", new() { ("", e.Message), ("", "run: python scripts/keymap.py --json scripts/keymap.json") }));
            return ("ARM - controls", sections);
        }
    }

    protected override void OnKeyDown(KeyEventArgs e)
    {
        base.OnKeyDown(e);
        if (e.Key is Key.Escape or Key.F1) Close();
    }
}
