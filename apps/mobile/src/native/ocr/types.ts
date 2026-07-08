export type BoundingBox = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type OcrWord = {
  text: string;
  confidence?: number;
  boundingBox: BoundingBox;
};

export type OcrLine = {
  id: string;
  text: string;
  confidence?: number;
  boundingBox: BoundingBox;
  words?: OcrWord[];
};

export type OcrTextBlock = {
  id: string;
  text: string;
  confidence?: number;
  boundingBox: BoundingBox;
  lines?: OcrLine[];
};

export type VisionOcrResult = {
  image: {
    width: number;
    height: number;
    orientation?: string;
  };
  blocks: OcrTextBlock[];
  fullText: string;
  engine: {
    name: "apple_vision";
    revision?: number;
    recognitionLevel: "fast" | "accurate";
  };
  capturedAt: string;
};

export type VisionOcrInput = {
  imageUri: string;
  recognitionLevel?: "fast" | "accurate";
  languageCorrection?: boolean;
};
