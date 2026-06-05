#include "ui/ChatScreen.h"
#include "ui/BroGlyph.h"
#include "ui/Theme.h"
#include "UiLayout.h"
#include "UiView.h"

namespace nb {

static void drawWave(M5Canvas &canvas, int x, int y, uint32_t frame) {
  for (int i = 0; i < 5; ++i) {
    int phase = (frame + i * 3) % 16;
    int h = 4 + (phase < 8 ? phase : 16 - phase) * 2;
    canvas.fillRoundRect(x + i * 5, y - h, 3, h, 1, theme::greenLight);
  }
}

static void drawThinkingDots(M5Canvas &canvas, int x, int y, uint32_t frame) {
  for (int i = 0; i < 3; ++i) {
    bool on = ((frame / 8) % 3) == (uint32_t)i;
    canvas.fillCircle(x + i * 8, y, on ? 3 : 2, on ? theme::coral : theme::muted);
  }
}

void ChatScreen::render(M5Canvas &canvas, uint32_t frame) {
  GlyphState gs = (phase_ == Phase::Streaming) ? GlyphState::Working : GlyphState::Idle;
  drawBroGlyph(canvas, glyphKindFor(bro_.avatar), gs, 16, 14, 10,
               phase_ == Phase::Streaming ? theme::coralLight : theme::text, frame);
  canvas.setFont(theme::fontName());
  canvas.setTextColor(theme::text);
  canvas.setCursor(34, 16);
  canvas.print(truncate(bro_.name, 14).c_str());
  uint16_t dot = (phase_ == Phase::Idle) ? theme::muted : theme::greenLight;
  canvas.fillCircle(canvas.width() - 12, 12, 4, dot);
  canvas.drawFastHLine(0, 26, canvas.width(), theme::line);

  int y = 34;
  if (!transcript_.empty()) {
    canvas.setFont(theme::fontSmall());
    canvas.setTextColor(theme::muted);
    canvas.setCursor(8, y);
    canvas.print(("> " + truncate(transcript_, 36)).c_str());
    y += 12;
  }
  canvas.setFont(theme::fontBody());
  canvas.setTextColor(theme::text);
  for (const auto &lineStr : wrapLines(reply_, 30, 3)) {
    canvas.setCursor(8, y);
    canvas.print(lineStr.c_str());
    y += 16;
  }

  int fy = canvas.height() - 6;
  if (phase_ == Phase::Recording) {
    drawWave(canvas, 8, fy, frame);
  } else if (phase_ == Phase::Streaming) {
    drawThinkingDots(canvas, 12, fy - 4, frame);
  }
  canvas.setFont(theme::fontSmall());
  canvas.setTextColor(phase_ == Phase::Idle ? theme::muted : theme::greenLight);
  canvas.setCursor(70, canvas.height() - 12);
  canvas.print(phaseLabel(phase_));
}

void ChatScreen::onKey(Key key) {
  if (key == Key::Back && onBack_) onBack_();
}

}  // namespace nb
