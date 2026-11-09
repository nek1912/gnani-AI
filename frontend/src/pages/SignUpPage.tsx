import { SignUp } from "@clerk/react";

export default function SignUpPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--canvas)] px-4">
      <SignUp routing="path" path="/sign-up" />
    </div>
  );
}
