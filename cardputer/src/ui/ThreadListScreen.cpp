#include "ui/ThreadListScreen.h"
#include "ui/Theme.h"
#include "UiLayout.h"

namespace nb {

static constexpr int kRows = 3;
static constexpr int kRowH = 32;
static constexpr int kHeaderH = 26;

void ThreadListScreen::render(M5Canvas &canvas, uint32_t frame) {
  (void)frame;
  canvas.setFont(theme::fontName());
  canvas.setTextColor(theme::text);
  canvas.setCursor(8, 16);
  canvas.print(truncate(broName_.empty() ? "Threads" : broName_, 18).c_str());
  canvas.setFont(theme::fontSmall());
  canvas.setTextColor(theme::muted);
  canvas.setCursor(176, 10);
  canvas.print("threads");
  canvas.drawFastHLine(0, kHeaderH, canvas.width(), theme::line);

  if (threads_.empty()) {
    canvas.setFont(theme::fontBody());
    canvas.setTextColor(theme::muted);
    canvas.setCursor(8, 56);
    canvas.print("No threads.");
    canvas.setFont(theme::fontSmall());
    canvas.setCursor(8, 78);
    canvas.print("Start one in the newbro web app.");
    return;
  }

  int top = listScrollTop(selected_, (int)threads_.size(), kRows);
  for (int row = 0; row < kRows && top + row < (int)threads_.size(); ++row) {
    int idx = top + row;
    const ThreadInfo &th = threads_[idx];
    int y = kHeaderH + 4 + row * kRowH;
    if (idx == selected_) {
      canvas.fillRoundRect(4, y, canvas.width() - 8, kRowH - 4, 6, theme::line);
      canvas.fillRect(4, y, 3, kRowH - 4, theme::coral);
    }
    canvas.setFont(theme::fontName());
    canvas.setTextColor(theme::text);
    canvas.setCursor(12, y + 3);
    canvas.print(truncate(th.title.empty() ? "(untitled)" : th.title, 22).c_str());

    canvas.setFont(theme::fontSmall());
    canvas.setTextColor(theme::muted);
    canvas.setCursor(12, y + 19);
    canvas.print(truncate(th.preview.empty() ? th.status : th.preview, 38).c_str());
  }

  canvas.setFont(theme::fontSmall());
  canvas.setTextColor(theme::muted);
  canvas.setCursor(8, canvas.height() - 12);
  canvas.print("; / .  pick     enter  open     `  back");
}

void ThreadListScreen::onKey(Key key) {
  if (key == Key::Back) {
    if (onBack_) onBack_();
    return;
  }
  if (threads_.empty()) return;
  if (key == Key::Up) selected_ = moveSelection(selected_, (int)threads_.size(), -1);
  else if (key == Key::Down) selected_ = moveSelection(selected_, (int)threads_.size(), +1);
  else if (key == Key::Enter && onPick_) onPick_(threads_[selected_]);
}

}  // namespace nb
