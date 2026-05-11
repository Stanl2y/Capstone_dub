// className 머지 유틸 — clsx + tailwind-merge (커스텀 fontSize 키를 알려줘야
// text-white 같은 색상 클래스와 충돌하지 않음)
import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// tailwind.config.ts 의 fontSize 토큰 — 색상이 아닌 글자 크기 그룹으로 인식시켜
// `text-body-sm-strong` 가 `text-white` 를 덮어쓰지 못하게 한다.
const CUSTOM_FONT_SIZES = [
  "display-xl",
  "display-lg",
  "heading-lg",
  "heading-md",
  "heading-sm",
  "body-md",
  "body-strong",
  "body-sm",
  "body-sm-strong",
  "caption-sm",
  "caption-strong",
  "data-label",
  "code-md",
  "code-sm",
  "button-md",
];

const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: CUSTOM_FONT_SIZES }],
    },
  },
});

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
