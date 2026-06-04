#include "ui/BroListScreen.h"
#include "ui/BroGlyph.h"
#include "ui/Theme.h"
#include "UiLayout.h"
#include "UiView.h"

namespace nb {

static constexpr int kRows = 3;
static constexpr int kRowH = 32;
static constexpr int kHeaderH = 26;

void BroListScreen::render(M5Canvas &canvas, uint32_t frame) {
  canvas.setFont(theme::fontName());
  canvas.setTextColor(theme::text);
  canvas.setCursor(8, 16);
  canvas.print("Your Bros");
  canvas.setFont(theme::fontSmall());
  canvas.setTextColor(theme::muted);
  canvas.setCursor(180, 10);
  canvas.printf("%d", (int)bros_.size());
  canvas.drawFastHLine(0, kHeaderH, canvas.width(), theme::line);

  if (bros_.empty()) {
    canvas.setFont(theme::fontBody());
    canvas.setTextColor(theme::muted);
    canvas.setCursor(8, 60);
    canvas.print("No bros yet");
    return;
  }

  int top = listScrollTop(selected_, (int)bros_.size(), kRows);
  for (int row = 0; row < kRows && top + row < (int)bros_.size(); ++row) {
    int idx = top + row;
    const Persona &b = bros_[idx];
    int y = kHeaderH + 4 + row * kRowH;
    bool sel = (idx == selected_);

    if (sel) {
      canvas.fillRoundRect(4, y, canvas.width() - 8, kRowH - 4, 6, theme::line);
      canvas.fillRect(4, y, 3, kRowH - 4, theme::coral);
    }

    GlyphState gs = b.busy ? GlyphState::Working : GlyphState::Idle;
    uint16_t glyphColor = b.busy ? theme::coralLight : theme::muted;
    drawBroGlyph(canvas, glyphKindFor(b.avatar), gs, 24, y + (kRowH - 4) / 2, 11, glyphColor, frame);

    canvas.setFont(theme::fontName());
    canvas.setTextColor(theme::text);
    canvas.setCursor(44, y + 4);
    canvas.print(truncate(b.name, 16).c_str());

    canvas.setFont(theme::fontSmall());
    canvas.setTextColor(b.busy ? theme::greenLight : theme::muted);
    canvas.setCursor(44, y + 20);
    canvas.print(b.busy ? "working" : "idle");
  }

  canvas.setFont(theme::fontSmall());
  canvas.setTextColor(theme::muted);
  canvas.setCursor(8, canvas.height() - 12);
  canvas.print("; / .  pick     enter  open");
}

void BroListScreen::onKey(Key key) {
  if (bros_.empty()) return;
  if (key == Key::Up) selected_ = moveSelection(selected_, (int)bros_.size(), -1);
  else if (key == Key::Down) selected_ = moveSelection(selected_, (int)bros_.size(), +1);
  else if (key == Key::Enter && onOpen_) onOpen_(bros_[selected_]);
}

}  // namespace nb
