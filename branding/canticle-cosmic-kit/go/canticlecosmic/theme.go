// Package canticlecosmic maps the Canticle Cosmic UI Kit to Lip Gloss v2.
//
// It owns presentation only. Bubble Tea models should continue to own state,
// input handling, updates, and commands.
package canticlecosmic

import (
	"image/color"

	"charm.land/lipgloss/v2"
)

// Palette is the truecolor Canticle palette. Lip Gloss downsampling remains
// responsible for terminals with smaller color profiles.
type Palette struct {
	Void       color.Color
	Night      color.Color
	Panel      color.Color
	Well       color.Color
	Bubble     color.Color
	Ink        color.Color
	Muted      color.Color
	Quiet      color.Color
	Line       color.Color
	LineBright color.Color
	Plasma     color.Color
	Magenta    color.Color
	Lavender   color.Color
	Orbit      color.Color
	Mint       color.Color
	Aqua       color.Color
	Sun        color.Color
	Comet      color.Color
	Danger     color.Color
	Blue       color.Color
	Ice        color.Color
}

// DefaultPalette returns the exact canticle-seam@1.0.0 colors used by the kit.
func DefaultPalette() Palette {
	return Palette{
		Void:       lipgloss.Color("#16161e"),
		Night:      lipgloss.Color("#1a1b26"),
		Panel:      lipgloss.Color("#1f2028"),
		Well:       lipgloss.Color("#13131a"),
		Bubble:     lipgloss.Color("#24253a"),
		Ink:        lipgloss.Color("#c0caf5"),
		Muted:      lipgloss.Color("#a9b1d6"),
		Quiet:      lipgloss.Color("#565f89"),
		Line:       lipgloss.Color("#3b3d57"),
		LineBright: lipgloss.Color("#565f89"),
		Plasma:     lipgloss.Color("#ff6090"),
		Magenta:    lipgloss.Color("#e478d0"),
		Lavender:   lipgloss.Color("#c4a7e7"),
		Orbit:      lipgloss.Color("#7dcfff"),
		Mint:       lipgloss.Color("#9ece6a"),
		Aqua:       lipgloss.Color("#73daca"),
		Sun:        lipgloss.Color("#e0af68"),
		Comet:      lipgloss.Color("#ff9e64"),
		Danger:     lipgloss.Color("#f7768e"),
		Blue:       lipgloss.Color("#7aa2f7"),
		Ice:        lipgloss.Color("#b4f9f8"),
	}
}

// Theme builds copy-safe Lip Gloss styles from one palette.
type Theme struct {
	Colors Palette
}

// New returns the default Canticle Cosmic theme.
func New() Theme {
	return Theme{Colors: DefaultPalette()}
}

// BrandMark renders the shared terminal prompt/cursor mark.
func (t Theme) BrandMark() lipgloss.Style {
	return lipgloss.NewStyle().
		Foreground(t.Colors.Mint).
		Background(t.Colors.Well).
		Border(lipgloss.RoundedBorder()).
		BorderForeground(t.Colors.Plasma).
		Bold(true).
		Padding(0, 1)
}

// BrandWord renders the Canticle company or SEAM product word beside the mark.
func (t Theme) BrandWord() lipgloss.Style {
	return lipgloss.NewStyle().
		Foreground(t.Colors.Plasma).
		Bold(true).
		PaddingLeft(1)
}

// Bubble renders the standard inflated panel silhouette available in terminals.
func (t Theme) Bubble() lipgloss.Style {
	return lipgloss.NewStyle().
		Foreground(t.Colors.Ink).
		Background(t.Colors.Bubble).
		Border(lipgloss.RoundedBorder()).
		BorderForeground(t.Colors.LineBright).
		Padding(1, 2)
}

// PlasmaBubble renders the primary branded panel variant.
func (t Theme) PlasmaBubble() lipgloss.Style {
	return t.Bubble().BorderForeground(t.Colors.Plasma)
}

// OrbitBubble renders an informational or focused panel variant.
func (t Theme) OrbitBubble() lipgloss.Style {
	return t.Bubble().BorderForeground(t.Colors.Orbit)
}

// MintBubble renders a successful or active panel variant.
func (t Theme) MintBubble() lipgloss.Style {
	return t.Bubble().BorderForeground(t.Colors.Mint)
}

// Sticker renders a short dark-on-bright section label.
func (t Theme) Sticker(background color.Color) lipgloss.Style {
	return lipgloss.NewStyle().
		Foreground(t.Colors.Void).
		Background(background).
		Bold(true).
		Padding(0, 1)
}

// Button renders an ordinary bounded action.
func (t Theme) Button() lipgloss.Style {
	return lipgloss.NewStyle().
		Foreground(t.Colors.Ink).
		Background(t.Colors.Panel).
		Border(lipgloss.RoundedBorder()).
		BorderForeground(t.Colors.LineBright).
		Bold(true).
		Padding(0, 1)
}

// PrimaryButton renders the main action in one view.
func (t Theme) PrimaryButton() lipgloss.Style {
	return t.Button().
		Foreground(t.Colors.Void).
		Background(t.Colors.Plasma).
		BorderForeground(t.Colors.Plasma)
}

// Focused wraps a component in the high-contrast orbit focus border.
func (t Theme) Focused() lipgloss.Style {
	return lipgloss.NewStyle().
		Border(lipgloss.ThickBorder()).
		BorderForeground(t.Colors.Orbit)
}

// Input renders an editable field. State and cursor behavior stay with the host.
func (t Theme) Input() lipgloss.Style {
	return lipgloss.NewStyle().
		Foreground(t.Colors.Ink).
		Background(t.Colors.Well).
		Border(lipgloss.RoundedBorder()).
		BorderForeground(t.Colors.LineBright).
		Padding(0, 1)
}

// TableHeader renders labels above data rows.
func (t Theme) TableHeader() lipgloss.Style {
	return lipgloss.NewStyle().
		Foreground(t.Colors.Lavender).
		Background(t.Colors.Night).
		Bold(true).
		Padding(0, 1)
}

// TableRow renders a normal data row.
func (t Theme) TableRow() lipgloss.Style {
	return lipgloss.NewStyle().
		Foreground(t.Colors.Muted).
		Background(t.Colors.Panel).
		Padding(0, 1)
}

// SelectedRow renders one explicit table selection.
func (t Theme) SelectedRow() lipgloss.Style {
	return lipgloss.NewStyle().
		Foreground(t.Colors.Void).
		Background(t.Colors.Plasma).
		Bold(true).
		Padding(0, 1)
}

// Quiet renders secondary descriptions and help text.
func (t Theme) Quiet() lipgloss.Style {
	return lipgloss.NewStyle().Foreground(t.Colors.Quiet)
}

// Error renders actionable failure text; callers should include words or icons.
func (t Theme) Error() lipgloss.Style {
	return lipgloss.NewStyle().Foreground(t.Colors.Danger).Bold(true)
}
