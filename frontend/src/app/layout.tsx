import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";
import { ToastProvider } from "@/components/Toast";
import { VoiceCommandProvider } from "@/components/voice/VoiceCommandProvider";

export const metadata: Metadata = {
  title: "Traceback",
  description: "A personal memory index for notes, tasks, and projects.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="h-full min-h-full bg-paper text-ink">
        <ToastProvider>
          <VoiceCommandProvider>
            <div className="flex h-screen min-w-[860px] overflow-hidden">
              <Sidebar />
              <main className="relative flex-1 overflow-y-auto">{children}</main>
            </div>
          </VoiceCommandProvider>
        </ToastProvider>
      </body>
    </html>
  );
}
