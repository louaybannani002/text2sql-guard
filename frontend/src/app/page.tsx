import { AskApp } from "@/components/ask/ask-app";
import { AuthProvider } from "@/components/auth/auth-provider";

export default function Home() {
  return (
    <AuthProvider>
      <AskApp />
    </AuthProvider>
  );
}
